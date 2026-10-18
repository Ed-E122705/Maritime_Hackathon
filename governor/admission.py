"""D1 admission: classify_admission() and explain_decision() (Whole_model.docx §8).

Verdicts (PDF D1):  YES · YES-IF (ranked displacement / throttle / interlock list) · NO ·
                    NOT-NOW (with the conditions and time of the next window)
Every sentence is generated from the constraint that actually bound the decision, with live numbers.
"""
from __future__ import annotations

import itertools
import time

from . import loader
from .model import GROUPS, KW, Problem, signature, solve_model

from decimal import ROUND_HALF_UP, Decimal


def _r(x, nd=2):
    """Round half-up for display (12.165 → 12.17, not the binary-float 12.16)."""
    return float(Decimal(repr(round(x, 9))).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP))


ROLE_LABEL = {"full": "full", "low": "low-power", "standby": "standby", "off": "off"}


# ----------------------------------------------------------------------------- independent evaluator
def evaluate(plan: dict, guests: dict, budget: dict, scen: list | None = None, ctx: dict | None = None) -> dict:
    """Recompute every resource from a plan in plain Python (used for numbers in sentences and as an
    independent cross-check of the solver)."""
    inst = [g for g, v in plan["installed"].items() if v]
    ev = {"violations": []}
    full = [g for g in inst if plan["mode_n"][g] == "full"]
    windows = [w for g in full for w in guests[g].windows]
    il = set(tuple(x) for x in plan["interlocks"])

    def blocked(S):
        for a, c in itertools.combinations(S, 2):
            if (a["id"], c["id"]) in il or (c["id"], a["id"]) in il:
                return True
        return False

    def kw(g, role):
        return guests[g].modes[role]["kw"]

    base_p = sum(kw(g, plan["mode_n"][g]) for g in inst)
    base_c = sum(kw(g, plan["mode_n"][g]) for g in inst if guests[g].chilled)
    worst_p, worst_c, case_p, case_c = base_p, base_c, (), ()
    line_worst = {l: 0.0 for l in budget["lines"]}
    for k in range(0, len(windows) + 1):
        for S in itertools.combinations(windows, k):
            if blocked(S):
                continue
            p_ = base_p + sum(w["delta_kw"] for w in S)
            c_ = base_c + sum(w["delta_kw"] for w in S if guests[w["guest"]].chilled)
            if p_ > worst_p:
                worst_p, case_p = p_, tuple(w["id"] for w in S)
            if c_ > worst_c:
                worst_c, case_c = c_, tuple(w["id"] for w in S)
            for l in budget["lines"]:
                on = [g for g in inst if plan["lines"].get(_point(guests, plan, g)) == l]
                lv = sum(kw(g, plan["mode_n"][g]) for g in on) + sum(w["delta_kw"] for w in S if w["guest"] in on)
                line_worst[l] = max(line_worst[l], lv)
    ev.update(power_n=worst_p, power_case=case_p, cool_n=worst_c, cool_case=case_c, lines=line_worst)
    ev["mass_kg"] = sum(guests[g].mass_kg for g in inst)
    ev["stab_kg_eq"] = sum(_cfg(guests, g, plan["config"][g]).stability_kg_eq for g in inst)
    bays = {"bay1": 0.0, "bay2": 0.0}
    bay_mass = {"bay1": 0.0, "bay2": 0.0}
    mast, hangar, roof = [], [], []
    for g in inst:
        for a in _cfg(guests, g, plan["config"][g]).assignments:
            if a["location"] in bays:
                bays[a["location"]] += a["fraction"]
                bay_mass[a["location"]] += a["mass_kg"]
            elif a["location"] == "mast_slot":
                mast.append(f"{g}.{a['component']}")
            elif a["location"] == "flight_deck_hangar":
                hangar.append(g)
            elif a["location"] == "hangar_roof":
                roof.append(f"{g}.{a['component']}")
    ev.update(bays=bays, bay_mass=bay_mass, mast=mast, hangar=sorted(set(hangar)), roof=roof)
    act = [g for g in inst if plan["mode_n"][g] in ("full", "low")]
    for key in ("satcom", "backbone", "los_radio"):
        ev[key] = sum(guests[g].data.get(key, 0) for g in act)
    for key in ("cpu_cores", "ram_gb", "accelerator_units", "storage_gb"):
        ev[key] = sum(float(guests[g].compute.get(key) or 0) for g in act)
    ev["degraded"] = {}
    for s in (scen if scen is not None else budget["degraded"]):
        md = {g: plan["mode_d"][g][s["name"]] for g in inst if s["name"] in plan["mode_d"][g]}
        wd = plan["windows_d"].get(s["name"], {})
        pw = sum(kw(g, md[g]) for g in md) + sum(w["delta_kw"] for g in md for w in guests[g].windows if wd.get(w["id"]))
        cl = sum(kw(g, md[g]) for g in md if guests[g].chilled) + \
            sum(w["delta_kw"] for g in md if guests[g].chilled for w in guests[g].windows if wd.get(w["id"]))
        ev["degraded"][s["name"]] = {"power": pw, "cooling": cl, "power_cap": s["power_kw"], "cooling_cap": s["cooling_kw"]}
    # cross-check every hard limit
    chk = [("power_normal", ev["power_n"], budget["power_kw"]), ("cooling_normal", ev["cool_n"], budget["cooling_kw"]),
           ("mass", ev["mass_kg"], budget["mass_kg"]), ("stability", ev["stab_kg_eq"], budget["stability_kg_eq"]),
           ("bay1", bays["bay1"], budget["bay1_fraction"]), ("bay2", bays["bay2"], budget["bay2_fraction"]),
           ("bay1_mass", bay_mass["bay1"], budget["bay1_max_kg"]), ("bay2_mass", bay_mass["bay2"], budget["bay2_max_kg"]),
           ("mast", len(mast), budget["mast_free"]), ("hangar", len(ev["hangar"]), budget["hangar_capacity"]), ("roof", len(roof), budget["roof_capacity"]),
           ("satcom", ev["satcom"], budget["satcom_mbps"]), ("backbone", ev["backbone"], budget["backbone_mbps"]),
           ("los_radio", ev["los_radio"], budget["los_radio_mbps"])]
    chk += [(k, ev[k], budget[k]) for k in ("cpu_cores", "ram_gb", "accelerator_units", "storage_gb")]
    chk += [(f"line_{l}", v, budget["line_kw"]) for l, v in line_worst.items()]
    for n, d in ev["degraded"].items():
        chk += [(f"{n}_power", d["power"], d["power_cap"]), (f"{n}_cooling", d["cooling"], d["cooling_cap"])]
    extra = []
    # degraded states: per-line limits, lost line, never above normal mode, running non-interruptible charge
    for s in (scen if scen is not None else budget["degraded"]):
        name = s["name"]
        wd = plan["windows_d"].get(name, {})
        for l in budget["lines"]:
            on = [g for g in inst if plan["lines"].get(_point(guests, plan, g)) == l]
            lv = sum(kw(g, plan["mode_d"][g][name]) for g in on) + \
                sum(w["delta_kw"] for g in on for w in guests[g].windows if wd.get(w["id"]))
            cap = 0 if s.get("lost_line") == l else budget["line_kw"]
            chk.append((f"{name}_line_{l}", lv, cap))
        for g in inst:
            if kw(g, plan["mode_d"][g][name]) > kw(g, plan["mode_n"][g]) + 1e-9:
                extra.append(f"{name}: {g} raised above its normal mode")
            for w in guests[g].windows:
                if not w["interruptible"] and plan["mode_n"][g] == "full" and not wd.get(w["id"]):
                    extra.append(f"{name}: {w['id']} non-interruptible but stopped")
            if guests[g].safety_critical and plan["mode_d"][g][name] not in ("full", "low"):
                extra.append(f"{name}: safety-critical {g} shed")
    # bay sharing (A.3): a guest that needs Bay 1 clear cannot share it
    for g in inst:
        if guests[g].needs_bay_clear and any(a["location"] == "bay1" and a["fraction"] < 1
                                             for a in _cfg(guests, g, plan["config"][g]).assignments):
            if bays["bay1"] > 0.5 + 1e-9:
                extra.append(f"{g} needs Bay 1 clear but shares it")
    if roof and budget.get("roof_requires_hangar_guest") and not ev["hangar"]:
        extra.append("hangar-roof item without a hangar guest")
    for g in inst:
        for ex in guests[g].excludes:
            if ex.get("type") == "absolute" and ex.get("other_guest") in inst:
                extra.append(f"{g} excludes {ex['other_guest']}")
        for rq in guests[g].requires:
            if rq.get("type") == "guest" and rq.get("guest") not in inst:
                extra.append(f"{g} requires {rq['guest']}")
    if ctx:
        cand, before = ctx.get("candidate"), ctx.get("installed") or {}
        minutes = guests[cand].install_port_minutes if cand and cand not in before else 0
        for g, cid in before.items():
            if g == cand or g not in guests:
                continue
            if g not in inst:
                minutes += guests[g].install_port_minutes * budget["removal_factor"]
            elif cid is not None and plan["config"][g] != cid:
                minutes += guests[g].install_port_minutes * (1 + budget["removal_factor"])
        ev["crane_min"] = minutes
        chk.append(("crane_time_min", minutes, budget["port_window_min"]))
    ev["violations"] = [f"{n}: {u:g} > {c:g}" for n, u, c in chk if u > c + 1e-6] + extra
    ev["margins"] = {n: (c - u) / c if c else 0 for n, u, c in chk if c and not n.startswith(("bay", "mast", "hangar", "roof", "crane"))}
    return ev


def _cfg(guests, g, cid):
    return next(c for c in guests[g].configs if c.id == cid)


def _point(guests, plan, g):
    return _cfg(guests, g, plan["config"][g]).point


# ----------------------------------------------------------------------------- sentences
def describe_group(grp: str, ev: dict, budget: dict, guests: dict, plan: dict, floor: dict | None = None) -> str:
    aboard = [g for g, v in plan.get("installed", {}).items() if v]
    def _case(c):
        return (f"when {' + '.join(c)} coincide" if c else
                f"continuous loads of {', '.join(aboard)}" + (" alone" if len(aboard) == 1 else ""))
    if grp == "power_normal":
        return (f"power at the {budget['power_band']} band: worst-case sustained demand {ev['power_n']:.1f} kW "
                f"({_case(ev['power_case'])}) vs {budget['power_kw']:g} kW reserve")
    if grp == "cooling_normal":
        return (f"cooling loop at {budget['seawater_c']:g} °C seawater has {budget['cooling_kw']:.0f} kW; "
                f"worst-case heat {ev['cool_n']:.1f} kW ({_case(ev['cool_case'])})")
    if grp == "power_line":
        l, v = max(ev["lines"].items(), key=lambda kv: kv[1])
        return f"power line {l}: {v:.1f} kW vs {budget['line_kw']:g} kW per line"
    if grp in ("power_degraded", "cooling_degraded"):
        f = floor or {}
        key = "power" if grp == "power_degraded" else "cooling"
        items = f.get("items", [])
        scens = budget.get("degraded") or []
        if key == "power":
            for s in scens:
                lost = s.get("lost_line")
                if lost in (None, "none"):
                    continue
                on = [(g, kw, why) for g, kw, why in items
                      if plan.get("config", {}).get(g) and plan["lines"].get(_point(guests, plan, g)) == lost]
                if on:
                    return (f"{s['label']}: mission line {lost} is lost but carries "
                            f"{sum(k for _, k, _ in on):g} kW that cannot be shed "
                            f"({', '.join(f'{g} {k:g} kW ({w})' for g, k, w in on)})")
        if not scens:
            return f"degraded state: {f.get(key, 0):.1f} kW cannot be shed"
        cap_of = lambda s: s["power_kw"] if key == "power" else s["cooling_kw"]
        s0 = max(scens, key=lambda s: f.get(key, 0) - cap_of(s))      # the state the floor overruns most
        on = items if key == "power" else [(g, k, w) for g, k, w in items if guests[g].chilled]
        parts = ", ".join(f"{g} {kw:g} kW ({why})" for g, kw, why in on)
        return (f"{s0['label']}: {f.get(key, 0):.1f} kW cannot be shed ({parts}) vs {cap_of(s0):g} kW")
    if grp == "mass":
        return f"mass {_r(ev['mass_kg']/1000):.2f} t vs {budget['mass_kg']/1000:g} t margin"
    if grp == "stability":
        return f"stability {_r(ev['stab_kg_eq']/1000):.2f} t-eq vs {budget['stability_kg_eq']/1000:g} t-eq budget"
    if grp == "deck_space":
        occ = []
        for g, cid in plan["config"].items():
            for a in _cfg(guests, g, cid).assignments:
                if a["location"] in ("bay1", "bay2"):
                    occ.append(f"{g} {a['fraction']:g}×{a['location']}")
        b1, b2 = ev["bays"]["bay1"], ev["bays"]["bay2"]
        clear = [g for g in plan["config"] if guests[g].needs_bay_clear and any(
            a["location"] == "bay1" and a["fraction"] == 0.5 for a in _cfg(guests, g, plan["config"][g]).assignments)]
        extra = f"; {', '.join(clear)} needs Bay 1 to itself (deck around bay clear)" if clear else ""
        return f"deck: Bay 1 asked for {b1:g} of 1, Bay 2 for {b2:g} of 1 ({', '.join(occ)}){extra}"
    if grp == "mast":
        return f"mast: {len(ev['mast'])} items ({', '.join(ev['mast'])}) for {budget['mast_free']} free slot(s)"
    if grp == "hangar":
        return f"flight-deck hangar/roof: {', '.join(ev['hangar'] + ev['roof'])} compete for one position each"
    if grp in ("satcom", "backbone", "los_radio"):
        return f"{grp}: {ev[grp]:g} Mbit/s vs {budget[grp + '_mbps']:g} Mbit/s"
    if grp == "compute":
        worst = max(("cpu_cores", "ram_gb", "accelerator_units", "storage_gb"), key=lambda k: ev[k] / max(budget[k], 1e-9))
        return f"compute: {worst} {ev[worst]:g} vs {budget[worst]:g} allocatable"
    if grp == "installation_time":
        return f"crane time exceeds the {budget['port_window_min']/60:g} h port window"
    if grp == "solver_timeout":
        return "solver hit its time limit before proving an answer"
    return grp


def degraded_floor(plan: dict, guests: dict, budget: dict) -> dict:
    """What cannot be shed when a genset trips: safety-critical floors and running non-interruptible windows."""
    items = []
    for g, inst in plan["installed"].items():
        if not inst:
            continue
        G = guests[g]
        if G.safety_critical:
            role = "low" if "low" in G.modes else "full"
            items.append((g, G.modes[role]["kw"], "safety-critical floor"))
        for w in G.windows:
            if not w["interruptible"] and plan["mode_n"].get(g) == "full":
                items.append((g, w["total_kw"], f"{w['id']} non-interruptible"))
    pw = sum(k for _, k, _ in items)
    cl = sum(k for g, k, _ in items if guests[g].chilled)
    return {"items": items, "power": pw, "cooling": cl}


# ----------------------------------------------------------------------------- envelope & rules
def envelope_operability(guests: dict, inst: list, raw: dict) -> list[str]:
    ship = raw["ship"]
    env = ship["envelope"]
    bands = {b: ship["speed_bands"][b] for b in env["speed_bands"]}
    notes = []
    for g in inst:
        for om in guests[g].op_modes:
            reqs = om.get("requirements", [])
            lo, hi = 0.0, 99.0
            for r in reqs:
                if r["field"] == "navigation.speed_knots":
                    v = r["value"]
                    if r["operator"] == "eq":
                        lo, hi = max(lo, v), min(hi, v)
                    elif r["operator"] == "lte":
                        hi = min(hi, v)
                    elif r["operator"] == "gte":
                        lo = max(lo, v)
            msgs = []
            if lo > 0 or hi < 99:
                ok = [b for b, (a, z) in bands.items() if not (z < lo or a > hi)]
                msgs.append(f"speed {lo:g}–{hi:g} kn → " + (f"only in {', '.join(ok)} band" if ok else "NEVER inside the envelope speed bands"))
            for r in reqs:
                if r["field"] == "environment.sea_state" and r["operator"] == "lte" and r["value"] < env["sea_state_max"]:
                    msgs.append(f"closed above sea state {r['value']} (envelope up to {env['sea_state_max']})")
                if r["field"] == "environment.wind_knots" and r["operator"] == "lte" and r["value"] < env["wind_kn_max"]:
                    msgs.append(f"closed above {r['value']} kn wind (envelope up to {env['wind_kn_max']} kn)")
            if msgs:
                notes.append(f"{g} {om['id']}: " + "; ".join(msgs))
    return notes


def standing_rules(guests: dict, inst: list, plan: dict) -> list[str]:
    seen, rules = set(), []
    for g in inst:
        for my_mode, other, other_mode, reason in guests[g].conflicts:
            if other in inst:
                key = tuple(sorted([(g, my_mode), (other, other_mode)]))
                if key not in seen:
                    seen.add(key)
                    rules.append(f"{g}.{my_mode} ✕ {other}.{other_mode}: {reason}")
    for a, b in plan.get("interlocks", []):
        rules.append(f"{a} ✕ {b}: governor interlock — never run both sustained draws at the same time")
    return rules


# ----------------------------------------------------------------------------- main entry
def build_problem(raw: dict, guests: dict, scenario: dict, priority: str, **kw) -> Problem:
    budget = loader.load_ship_budget(raw)
    installed = dict(scenario.get("installed") or {})
    cand = scenario.get("candidate")
    in_play = {g: guests[g] for g in list(installed) + ([cand] if cand else []) if g in guests}
    return Problem(guests=in_play, weights=raw["priority"][priority]["weights"], budget=budget,
                   installed=installed, candidate=cand, time_limit_s=raw["ship"].get("solver_time_limit_s", 10), **kw)


def classify_admission(raw: dict, scenario: dict, priority: str, n_alternatives: int = 4) -> dict:
    t0 = time.perf_counter()
    guests = loader.load_guest_data(raw)
    cand = scenario.get("candidate")
    out = {"candidate": cand, "priority": priority, "installed_before": scenario.get("installed"),
           "schema_errors": {g: loader.validate_manifest(c, raw["schema"]) for g, c in raw["card"].items()}}
    out["schema_errors"] = {g: e for g, e in out["schema_errors"].items() if e}
    if cand in out["schema_errors"]:
        out.update(verdict="NO", sentence=f"Refused: {cand} manifest fails the schema ({out['schema_errors'][cand][0]}).")
        return out
    # A custom guest with unknown installation permission, crew or duration
    # must NOT be accepted as a zero-minute / zero-crew installation.
    if cand and cand not in (scenario.get("installed") or {}):
        unknown_install = [item for item in raw["card"][cand]["installation"]
                           if item.get("component_ids") and any(item.get(key) is None
                              for key in ("port_only", "crew_required", "duration_minutes"))]
        if unknown_install:
            out.update(verdict="NOT-NOW", binding=["installation_evidence"],
                       sentence=(f"Installation not authorized for {cand}: manifest lacks port permission, "
                                 "crew requirement or duration. Supply reviewed installation values before "
                                 "running a physical admission."),
                       physical_crosscheck={"status":"UNKNOWN","reason":"Installation prerequisites undefined"})
            out["elapsed_s"] = round(time.perf_counter() - t0, 3)
            return out
    state = dict(raw["ship"]["current_state"])
    state.update(scenario.get("state", {}))
    out["state"] = state
    if cand and all(c.issues for c in guests[cand].configs):
        why = "; ".join(f"{c.id}: {', '.join(c.issues)}" for c in guests[cand].configs)
        out.update(verdict="NO", binding=["position"], sentence=f"Refused: no position aboard can take {cand} ({why}).")
        out["elapsed_s"] = round(time.perf_counter() - t0, 3)
        return out
    if state.get("location") == "at_sea":
        out.update(at_sea_decision(raw, guests, scenario, priority, state))
        out["elapsed_s"] = round(time.perf_counter() - t0, 3)
        return out

    budget = loader.load_ship_budget(raw)
    out["budget"] = {k: v for k, v in budget.items() if k not in ("degraded", "stress")}
    # 1) baseline: admit without touching anyone
    pb = build_problem(raw, guests, scenario, priority, baseline=True)
    base_plan, base_core = solve_model(pb, lexicographic=False)
    # 2) full optimization: removals, relocations, throttling, interlocks allowed
    pf = build_problem(raw, guests, scenario, priority)
    plan, core = solve_model(pf)
    if plan is None:
        # NOT-NOW if the only obstacle is the length of this port call
        demand = _demand_plan(raw, guests, scenario, priority, minimal=True)
        ev = evaluate(demand, guests, budget) if demand else None
        fl = degraded_floor(demand, guests, budget) if demand else None
        reasons = [describe_group(g, ev, budget, guests, demand, fl) if ev else g for g in core]
        relaxed = None
        if "installation_time" in core:
            pr_ = build_problem(raw, guests, scenario, priority, disabled_groups={"installation_time"})
            relaxed, _ = solve_model(pr_)
        if relaxed is not None:
            need_min = (guests[cand].install_port_minutes if cand not in scenario.get("installed", {}) else 0) + \
                relaxed["objective"]["disruption_min"]
            acts = "; ".join(a["text"] for a in _actions(relaxed, pr_, guests)) or "no change"
            out.update(verdict="NOT-NOW", binding=core, plan_if_time=relaxed,
                       sentence=(f"Not now: making room needs {need_min/60:g} h of crane work ({acts}) but this port "
                                 f"call allows {budget['port_window_min']/60:g} h; when: a port call of at least "
                                 f"{need_min/60:g} h."))
        else:
            out.update(verdict="NO", binding=core,
                       sentence=f"Refused: even after removing or throttling every removable guest, {'; '.join(reasons)}.")
        out["elapsed_s"] = round(time.perf_counter() - t0, 3)
        return out
    ev = evaluate(plan, guests, budget, ctx={"candidate": cand, "installed": scenario.get("installed")})
    out["plan"] = plan
    out["usage"] = _usage_table(ev, budget)
    out["solver_crosscheck"] = ev["violations"]          # must be empty
    inst = [g for g, v in plan["installed"].items() if v]
    out["degraded"] = _degraded_statement(plan, guests, budget)
    out["stress"] = stress_tests(raw, guests, scenario, priority, plan, budget) + comms_stress(plan, guests, raw)
    out["operability"] = envelope_operability(guests, inst, raw)
    never = [n for n in out["operability"] if n.startswith(f"{cand} ") and "NEVER" in n]
    if never and len(never) == len([m for m in guests[cand].op_modes if any(
            r["field"] == "navigation.speed_knots" for r in m.get("requirements", []))]):
        out["warning"] = f"{cand} can never meet its speed conditions inside this envelope: {'; '.join(never)}"
    out["standing_rules"] = standing_rules(guests, inst, plan)
    out["placement"] = _placement_text(plan, guests)
    tight = min(((k, v) for k, v in ev["margins"].items()), key=lambda kv: kv[1])
    if base_plan is not None:
        out.update(verdict="YES", binding=[],
                   sentence=(f"Admitted: {cand} fits the {budget['power_band']}-band envelope at "
                             f"{budget['seawater_c']:g} °C with no change to installed guests; tightest margin is "
                             f"{tight[0]} at {tight[1]*100:.0f} % free. {out['degraded']['sentence']}"))
        out["actions"] = []
    else:
        demand = _demand_plan(raw, guests, scenario, priority, minimal=False)
        dev = evaluate(demand, guests, budget)
        fl = degraded_floor(demand, guests, budget)
        out["binding"] = base_core
        out["binding_text"] = [describe_group(g, dev, budget, guests, demand, fl) for g in base_core]
        out["actions"] = _actions(plan, pf, guests)
        act_txt = "; ".join(a["text"] for a in out["actions"]) or "no change"
        out.update(verdict="YES-IF",
                   sentence=(f"Admitted if: {act_txt}. Binding: {'; '.join(out['binding_text'])}. "
                             f"{out['degraded']['sentence']}"))
    # net mission value under this priority file: before (installed, all full) vs after
    w = raw["priority"][priority]["weights"]
    u_before = sum(w.get(g, 1) * guests[g].modes["full"]["capability"] for g in scenario.get("installed", {}))
    u_after = plan["objective"]["U_normal"]
    out["value"] = {"before": u_before, "after": u_after, "candidate_weight": w.get(cand, 1)}
    if u_after < u_before - 1e-9:
        out["recommendation"] = (f"Net mission value under '{priority}' falls from {u_before:g} to {u_after:g}: "
                                 f"admitting {cand} (weight {w.get(cand, 1):g}) costs more than it brings — "
                                 f"the captain may prefer to decline.")
        out["sentence"] += " " + out["recommendation"]
    out["alternatives"] = alternatives(pf, plan, guests, budget, n_alternatives)
    out["placement_options"] = placement_options(pf, plan, guests, budget)
    out["elapsed_s"] = round(time.perf_counter() - t0, 3)
    out["within_30s"] = out["elapsed_s"] <= raw["ship"]["response_time"]["admission_s"]
    # Independent selected-state physical screen; separate from optimizer's
    # mission envelope and never presented as full admission certification.
    from .integration import crosscheck_admission
    out["physical_crosscheck"] = crosscheck_admission(out, raw, scenario)
    if out["physical_crosscheck"]["status"] == "FAIL":
        out["integration_warning"] = "Physical model rejects the selected state: inspect failed_constraints before implementing this plan."
    return out


def _demand_plan(raw, guests, scenario, priority, minimal: bool):
    """A plan computed with every capacity limit switched off — used only for the numbers in a
    refusal sentence. minimal=True removes/throttles everything removable (for NO)."""
    p = build_problem(raw, guests, scenario, priority, baseline=not minimal,
                      disabled_groups=set(GROUPS))
    if minimal:
        p.allow_removal = True
    from .model import build_model, _solver, extract
    b = build_model(p)
    b.m.ClearAssumptions()
    if minimal:
        b.m.Minimize(b.worst_power + sum(b.inst.values()))
    else:
        b.m.Maximize(b.placement_score)
    s = _solver(p)
    st = s.Solve(b.m)
    from ortools.sat.python import cp_model
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return extract(b, s)


def _usage_table(ev, budget):
    rows = [("power (normal, worst case)", ev["power_n"], budget["power_kw"], "kW"),
            ("cooling (normal, worst case)", ev["cool_n"], budget["cooling_kw"], "kW")]
    for n, d in ev["degraded"].items():
        rows.append((f"power ({n})", d["power"], d["power_cap"], "kW"))
    rows += [("mass", ev["mass_kg"] / 1000, budget["mass_kg"] / 1000, "t"),
             ("stability", ev["stab_kg_eq"] / 1000, budget["stability_kg_eq"] / 1000, "t-eq"),
             ("Bay 1", ev["bays"]["bay1"], budget["bay1_fraction"], "bay"), ("Bay 2", ev["bays"]["bay2"], budget["bay2_fraction"], "bay"),
             ("mast slots", len(ev["mast"]), budget["mast_free"], "slot"),
             ("SATCOM", ev["satcom"], budget["satcom_mbps"], "Mbit/s"),
             ("backbone", ev["backbone"], budget["backbone_mbps"], "Mbit/s"),
             ("LOS radio", ev["los_radio"], budget["los_radio_mbps"], "Mbit/s"),
             ("CPU cores", ev["cpu_cores"], budget["cpu_cores"], "cores"),
             ("RAM", ev["ram_gb"], budget["ram_gb"], "GB"),
             ("accelerators", ev["accelerator_units"], budget["accelerator_units"], "units")]
    for l, v in ev["lines"].items():
        rows.append((f"line {l} (worst case)", v, budget["line_kw"], "kW"))
    return [{"resource": r, "used": _r(u), "capacity": _r(c), "unit": un,
             "free_pct": round(100 * (c - u) / c, 1) if c else None} for r, u, c, un in rows]


def _degraded_statement(plan, guests, budget):
    out = {"changes": {}, "sentence": ""}
    for s in budget["degraded"]:
        ch = []
        for g, md in plan["mode_d"].items():
            r = md.get(s["name"])
            if r and r != plan["mode_n"][g]:
                ch.append(f"{g} {ROLE_LABEL[plan['mode_n'][g]]}→{ROLE_LABEL[r]}")
            for w in guests[g].windows:
                if w["interruptible"] and plan["mode_n"][g] == "full" and not plan["windows_d"].get(s["name"], {}).get(w["id"]):
                    ch.append(f"{w['id']} deferred")
        out["changes"][s["name"]] = ch
        out["sentence"] += (f"With {s['label']}: holds unchanged. " if not ch
                            else f"With {s['label']}: holds after {', '.join(ch)}. ")
    return out


def _actions(plan, p, guests):
    acts = []
    for g in plan["removed"]:
        lost = p.weights.get(g, 1) * guests[g].modes["full"]["capability"]
        acts.append({"type": "remove", "guest": g, "capability_lost": lost,
                     "text": f"remove {g} ({guests[g].name}; loses {lost:g} weighted capability, "
                             f"{guests[g].install_port_minutes/60:g} h crane work)"})
    for g in plan["relocated"]:
        acts.append({"type": "relocate", "guest": g, "capability_lost": 0,
                     "text": f"move {g} from {p.installed[g]} to {plan['config'][g]}"})
    for g, r in plan["mode_n"].items():
        if r != "full":
            G = guests[g]
            lost = p.weights.get(g, 1) * (G.modes["full"]["capability"] - G.modes[r]["capability"])
            acts.append({"type": "throttle", "guest": g, "capability_lost": lost,
                         "text": f"run {g} {ROLE_LABEL[r]} ({G.modes['full']['kw']:g}→{G.modes[r]['kw']:g} kW; "
                                 f"loses {lost:g} weighted capability)"})
    for a, b in plan["interlocks"]:
        acts.append({"type": "interlock", "guest": f"{a}/{b}", "capability_lost": 0,
                     "text": f"interlock {a} and {b} (never simultaneous; one waits)"})
    acts.sort(key=lambda x: (x["capability_lost"], x["type"]))
    return acts


def alternatives(p: Problem, best: dict, guests, budget, k: int) -> list[dict]:
    """Next-best distinct plans (different removals / throttles / interlocks), in objective order."""
    out = []
    nogoods = [signature(best, p)]
    kept = [set(a["text"] for a in _actions(best, p, guests))]
    tries = 0
    while len(out) < k and tries < 3 * k + 3:
        tries += 1
        q = Problem(**{**p.__dict__, "no_goods": list(nogoods)})
        plan, core = solve_model(q)
        if plan is None:
            break
        nogoods.append(signature(plan, q))
        acts = _actions(plan, q, guests)
        aset = set(a["text"] for a in acts)
        if any(prev <= aset for prev in kept):
            continue          # a better plan already does a subset of these actions → dominated
        kept.append(aset)
        out.append({"actions": [a["text"] for a in acts] or ["no change"],
                    "capability_lost": round(sum(a["capability_lost"] for a in acts), 3),
                    "U_normal": plan["objective"]["U_normal"], "U_degraded": plan["objective"]["U_degraded"],
                    "MI_pct": plan["objective"]["MI_pct"], "placement": _placement_text(plan, guests)})
    return out


def placement_options(p: Problem, best: dict, guests, budget) -> list[dict]:
    """D2: every position the candidate's card allows, with why it was chosen or rejected."""
    cand = p.candidate
    out = []
    for c in guests[cand].configs:
        row = {"config": c.id, "preferred": c.preferred, "chosen": best["config"].get(cand) == c.id}
        if c.issues:
            row.update(status="impossible", reason="; ".join(c.issues))
        elif row["chosen"]:
            row.update(status="chosen", U=best["objective"]["U_normal"], margin=best["objective"]["MI_pct"])
        else:
            q = Problem(**{**p.__dict__, "force_config": {**p.force_config, cand: c.id}})
            plan, core = solve_model(q)
            if plan is None:
                row.update(status="infeasible", reason=", ".join(core))
            else:
                ob, bo = plan["objective"], best["objective"]
                worse = [k for k in ("U_normal", "U_degraded") if ob[k] < bo[k] - 1e-9]
                why = (f"lower {' and '.join(worse)} ({ob['U_normal']:g} vs {bo['U_normal']:g})" if worse else
                       f"more disruption ({ob['disruption_min']} vs {bo['disruption_min']} crane-min)" if ob['disruption_min'] > bo['disruption_min'] else
                       f"less margin ({ob['MI_pct']}% vs {bo['MI_pct']}%)" if ob['MI_pct'] < bo['MI_pct'] else
                       "equal on all objectives; preferred position or tie-break chose the other")
                row.update(status="rejected", reason=why, U=ob["U_normal"], margin=ob["MI_pct"],
                           actions=[a["text"] for a in _actions(plan, q, guests)])
        out.append(row)
    return out


def comms_stress(plan, guests, raw):
    """A.5/A.6: emission silence zeroes SATCOM and radio; SATCOM may fall to its low end."""
    inst = [g for g, v in plan["installed"].items() if v]
    lost, stops = [], []
    for g in inst:
        for dl in guests[g].card["resources"]["data_links"]:
            if dl["disabled_in_emission_silence"]:
                lost.append(f"{g} {dl['type']}")
        for om in guests[g].op_modes:
            if any(r["field"] == "platform.emission_state" and r["operator"] == "neq" and r["value"] == "silent"
                   for r in om.get("requirements", [])):
                stops.append(f"{g}.{om['id']}")
        for ev_ in guests[g].card.get("special_events", []):
            if ev_.get("type") == "emission_silence":
                stops.append(f"{g} {ev_['action'].replace('_', ' ')} ({ev_.get('additional_requirement', '')})")
    out = [{"state": "emission silence", "holds": True,
            "sentence": "emission silence: SATCOM and radio go to zero — " +
                        (f"links lost: {', '.join(lost)}; " if lost else "no guest link lost; ") +
                        (f"stops: {', '.join(stops)}" if stops else "no guest mode stops")}]
    low = raw["ship"]["data"]["satcom_low_mbps"]
    dem = sum(guests[g].data.get("satcom", 0) for g in inst if plan["mode_n"][g] in ("full", "low"))
    out.append({"state": f"SATCOM at {low:g} Mbit/s", "holds": dem <= low,
                "sentence": f"SATCOM at its {low:g} Mbit/s low end (A.5): demand {dem:g} Mbit/s" +
                            (" fits" if dem <= low else f" — shore links share {low:g} Mbit/s; G5 connectivity degrades first")})
    return out


def stress_tests(raw, guests, scenario, priority, plan, budget):
    """Same installation, harsher states (A.2 cooling loss, genset+cooling). Governor may only throttle/shed."""
    res = []
    for s in budget["stress"]:
        p = build_problem(raw, guests, scenario, priority,
                          fixed={"installed": plan["installed"], "config": plan["config"], "mode_n": plan["mode_n"]},
                          degraded=[s])
        sp, core = solve_model(p, lexicographic=True)
        if sp is None:
            fl = degraded_floor(plan, guests, budget)
            res.append({"state": s["label"], "holds": False,
                        "sentence": f"{s['label']}: cannot hold — {fl['power']:.0f} kW power / {fl['cooling']:.0f} kW heat "
                                    f"cannot be shed ({', '.join(f'{g} {k:g} kW' for g, k, _ in fl['items'])}); binding {', '.join(core)}"})
            continue
        ch = []
        for g, md in sp["mode_d"].items():
            r = md.get(s["name"])
            if r and r != plan["mode_n"][g]:
                ch.append(f"{g} {ROLE_LABEL[plan['mode_n'][g]]}→{ROLE_LABEL[r]}")
            for w in guests[g].windows:
                if w["interruptible"] and plan["mode_n"][g] == "full" and not sp["windows_d"].get(s["name"], {}).get(w["id"]):
                    ch.append(f"{w['id']} deferred")
        res.append({"state": s["label"], "holds": True, "changes": ch,
                    "sentence": f"{s['label']}: holds" + (f" after {', '.join(ch)}" if ch else " unchanged")})
    return res


def _placement_text(plan, guests):
    out = {}
    for g, cid in plan["config"].items():
        c = _cfg(guests, g, cid)
        locs = ", ".join(f"{a['component']}@{a['location']}" + (f"({a['fraction']:g})" if a["fraction"] else "") for a in c.assignments)
        out[g] = f"{cid} [{locs}] line={plan['lines'].get(c.point)}" + ("" if c.preferred else " (tolerated, not preferred)")
    return out


# ----------------------------------------------------------------------------- A′: under way
def at_sea_decision(raw, guests, scenario, priority, state):
    ship = raw["ship"]
    cand = scenario["candidate"]
    G = guests[cand]
    win = ship["installation"]["at_sea_window"]
    crew = state.get("crew", 0)
    if scenario.get("swap"):
        return _swap_decision(raw, guests, scenario, state)
    port_only = [c for c in G.components if c in G.port_only_components]
    heavy = [c for c, kg in G.components.items() if kg > ship["installation"]["at_sea_max_item_kg"]]
    out = {"mode": "at_sea"}
    # what the port verdict will be at the next port call
    port_scn = dict(scenario)
    port_scn["state"] = {"location": "port"}
    raw_port = dict(raw)
    raw_port["ship"] = dict(raw["ship"])
    raw_port["ship"]["current_state"] = dict(raw["ship"]["current_state"], location="port")
    nxt = classify_admission(raw_port, port_scn, priority, n_alternatives=0)
    when = f"next port call (within {ship['envelope']['days_without_port']} days)"
    if crew == 0:
        levers = _logical_levers(guests, scenario, raw, priority)
        out.update(verdict="NOT-NOW",
                   sentence=(f"Not now: no crew aboard, so nothing physical can change (A.11); when: {when}, where the "
                             f"verdict would be {nxt['verdict']}. Logical reconfiguration available now: {levers}."),
                   next_port_verdict=nxt["verdict"], next_port_sentence=nxt.get("sentence"))
        return out
    if port_only or heavy:
        why = []
        if port_only:
            why.append(f"{', '.join(port_only)} {'is' if len(port_only)==1 else 'are'} port-only")
        if heavy:
            why.append(f"{', '.join(heavy)} exceed{'s' if len(heavy)==1 else ''} the {ship['installation']['at_sea_max_item_kg']} kg at-sea limit")
        out.update(verdict="NOT-NOW",
                   sentence=f"Not now: {'; '.join(why)} (A.11); when: {when}, where the verdict would be {nxt['verdict']}.",
                   next_port_verdict=nxt["verdict"], next_port_sentence=nxt.get("sentence"))
        return out
    # portable item: check the installation window now
    unmet, minutes = [], 0
    if state.get("sea_state", 9) > win["sea_state_max"]:
        unmet.append(f"sea state {state.get('sea_state')} > {win['sea_state_max']} (wait for weather)")
    if state.get("wind_kn", 99) > win["wind_kn_max"]:
        unmet.append(f"wind {state.get('wind_kn')} kn > {win['wind_kn_max']} kn (wait for weather)")
    lo, hi = win["speed_kn"]
    if not (lo <= state.get("speed_kn", 0) <= hi):
        unmet.append(f"speed {state.get('speed_kn')} kn not in {lo}–{hi} kn")
        minutes += ship["state_transitions"]["speed_band_change_min"]
    if state.get("course") != "steady":
        unmet.append("course not steady")
        minutes += ship["state_transitions"]["course_settle_min"]
    if state.get("deck") != "clear":
        dc = ship["state_transitions"]["deck_clear_min"].get(crew)
        unmet.append("deck occupied")
        minutes += dc or 0
    if state.get("survey_vehicle_listening"):
        unmet.append("survey vehicle listening")
    need = win["crew_flight_deck"]
    if crew < need:
        unmet.append(f"{crew} crew < {need} needed")
    if unmet:
        out.update(verdict="NOT-NOW", sentence=f"Not now: installation window closed — {'; '.join(unmet)}; "
                                               f"controllable conditions can be set in ~{minutes} min.")
    else:
        out.update(verdict="YES", sentence="Admitted under way: installation window open now.")
    return out


def _window_unmet(raw, state, crew_needed, ramp=False):
    ship = raw["ship"]
    win = ship["installation"]["at_sea_window"]
    st = ship["state_transitions"]
    crew = state.get("crew", 0)
    unmet, minutes, weather = [], 0, False
    if state.get("sea_state", 9) > win["sea_state_max"]:
        unmet.append(f"sea state {state.get('sea_state')} > {win['sea_state_max']}")
        weather = True
    if state.get("wind_kn", 99) > win["wind_kn_max"]:
        unmet.append(f"wind {state.get('wind_kn')} kn > {win['wind_kn_max']} kn")
        weather = True
    lo, hi = win["speed_kn"]
    if not (lo <= state.get("speed_kn", 0) <= hi):
        unmet.append(f"speed {state.get('speed_kn')} kn → {lo}–{hi} kn")
        minutes += st["speed_band_change_min"]
    if state.get("course") != "steady":
        unmet.append("course → steady")
        minutes += st["course_settle_min"]
    if state.get("deck") != "clear":
        dc = st["deck_clear_min"].get(crew)
        if dc is None:
            unmet.append("deck occupied and no crew to clear it")
        else:
            unmet.append(f"clear the deck ({dc} min with {crew} crew)")
            minutes += dc
    if state.get("survey_vehicle_listening"):
        unmet.append("wait for the survey vehicle to stop listening")
    if crew < crew_needed:
        unmet.append(f"{crew} crew aboard < {crew_needed} needed")
    return unmet, minutes, weather


def _swap_decision(raw, guests, scenario, state):
    gid, comp = scenario["swap"].split(".")
    G = guests[gid]
    entry = next((e for e in G.install_entries if comp in e["component_ids"] and not e["port_only"]), None)
    crew = state.get("crew", 0)
    if gid not in scenario.get("installed", {}) or entry is None:
        return {"mode": "at_sea", "verdict": "NO",
                "sentence": f"Refused: {scenario['swap']} has no at-sea installation path on the {gid} card."}
    if crew == 0:
        return {"mode": "at_sea", "verdict": "NOT-NOW",
                "sentence": f"Not now: no crew aboard, so the {comp} swap ({entry['crew_required']} people, "
                            f"{entry['duration_minutes']:g} min) is impossible; when: next crewed window or port call."}
    unmet, minutes, weather = _window_unmet(raw, state, entry["crew_required"])
    if not unmet:
        return {"mode": "at_sea", "verdict": "YES",
                "sentence": f"Admitted under way: installation window open; {comp} swap takes "
                            f"{entry['duration_minutes']:g} min with {entry['crew_required']} crew."}
    when = (f"after ~{minutes} min to set speed/course/deck" + (" and once the weather is inside the window limits" if weather else ""))
    return {"mode": "at_sea", "verdict": "NOT-NOW",
            "sentence": f"Not now: installation window closed — {'; '.join(unmet)}; when: {when}; "
                        f"then {entry['duration_minutes']:g} min with {entry['crew_required']} crew.",
            "window_unmet": unmet}


def _logical_levers(guests, scenario, raw, priority):
    w = raw["priority"][priority]["weights"]
    lev = []
    for g in scenario.get("installed", {}):
        G = guests[g]
        if "low" in G.modes:
            free = G.modes["full"]["kw"] - G.modes["low"]["kw"]
            lev.append(f"throttle {g} to low power (frees {free:g} kW, costs {w.get(g,1)*(1-G.modes['low']['capability']):g} weighted capability)")
    lev.append("re-task or re-allocate compute among installed guests")
    return "; ".join(lev)
