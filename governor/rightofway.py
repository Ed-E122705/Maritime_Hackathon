"""Scenario B: D3 right of way + D4 degradation on a deterministic minute-step simulator.

D3  When two admitted guests need incompatible ship states, the governor
      1. finds the conflicting fields from the cards' operational-mode requirements (+ declared implications),
      2. applies hard constraints first (battery deadline, A.6 transition times, crew confirmation policy),
      3. simulates every remaining option over the horizon (D4 included) and scores it with the priority file:
            U = Σ_g  w_g × (capability-minutes of g) / horizon
      4. picks the highest U and states the rationale and the cost to the loser in one sentence each.
D4  Whenever demand exceeds the reserve (or cooling), it throttles before it sheds, in a declared order:
      cheapest weighted capability lost per kW freed first, all throttles/deferrals before any shed;
      never touches protected loads (the D3 winner's critical draw, a running non-interruptible charge,
      safety-critical guests). Restores in reverse order when headroom returns.
Nothing here is scenario-specific code: guests, weights, timings and limits come from the cards and config.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import loader

ROOT = loader.ROOT


def load_ops():
    return yaml.safe_load(open(ROOT / "config/ops.yaml"))


# ----------------------------------------------------------------------------- ship-state conditions
def _ship_value(ship: dict, env: dict, fld: str):
    return {
        "navigation.speed_knots": ship["speed_kn"],
        "navigation.course_keeping": ship["course"],
        "navigation.noise_level": ship["noise"],
        "navigation.manoeuvre_freedom": ship["course"] == "free" or ship.get("posture") == "flight_ops",
        "platform.deck_machinery_active": ship["deck_machinery"],
        "platform.flight_deck_clear": ship["deck"] == "clear",
        "platform.deck_area_around_bay_clear": ship["deck"] == "clear",
        "platform.stern_ramp_in_use": ship["ramp_in_use"],
        "platform.stern_ramp_free": not ship["ramp_in_use"],
        "platform.emission_state": ship["emission"],
        "environment.sea_state": env["sea_state"],
        "environment.wind_knots": env["wind_kn"],
    }.get(fld)


def _ok(op, have, want):
    if have is None:
        return True
    return {"eq": have == want, "neq": have != want, "lte": have <= want, "gte": have >= want,
            "lt": have < want, "gt": have > want}[op]


def requirements(card: dict, mode_id: str) -> list:
    return next((m.get("requirements", []) for m in card["operational_modes"] if m["id"] == mode_id), [])


def conflicts_between(card_a, mode_a, card_b, mode_b, implications) -> list[str]:
    """Fields on which no single ship state satisfies both modes (card requirements + implications)."""
    def expand(reqs):
        out = list(reqs)
        for r in reqs:
            if r["field"] in implications and r["value"] is True:
                out += [{"field": i["field"], "operator": "eq", "value": i["value"], "reason": f"implied by {r['field']}"}
                        for i in implications[r["field"]]]
        return out
    ra, rb = expand(requirements(card_a, mode_a)), expand(requirements(card_b, mode_b))
    fields = sorted({r["field"] for r in ra} & {r["field"] for r in rb})
    out = []
    for f in fields:
        A = [r for r in ra if r["field"] == f]
        B = [r for r in rb if r["field"] == f]
        vals = sorted({r["value"] for r in A + B}, key=str)
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            grid = [x / 2 for x in range(0, 61)]
            sat = [x for x in grid if all(_ok(r["operator"], x, r["value"]) for r in A + B)]
            if not sat:
                out.append(f"{f.split('.')[-1]}: {card_a['id']} {_fmt(A)} vs {card_b['id']} {_fmt(B)}")
        else:
            cands = set(vals) | {"free", "steady", "quiet", "normal", "manoeuvring"}
            sat = [v for v in cands if all(_ok(r["operator"], v, r["value"]) for r in A + B)]
            if not sat:
                why = [r["reason"] for r in A + B if r.get("reason", "") and str(r["reason"]).startswith("implied")]
                out.append(f"{f.split('.')[-1]}: {card_a['id']} {_fmt(A)} vs {card_b['id']} {_fmt(B)}"
                           + (f" ({why[0]})" if why else ""))
    return out


def _fmt(rs):
    sym = {"eq": "=", "neq": "≠", "lte": "≤", "gte": "≥", "lt": "<", "gt": ">"}
    return " & ".join(f"{sym[r['operator']]}{r['value']}" for r in rs)


# ----------------------------------------------------------------------------- simulator
POSTURES = {
    # posture: ship-state targets the governor can request (A.6 variables)
    "survey":     {"speed_kn": None, "course": "steady", "noise": "quiet", "ramp_in_use": False},
    "flight_ops": {"speed_kn": None, "course": "free", "noise": "manoeuvring", "ramp_in_use": False},
    "ramp":       {"speed_kn": None, "course": "steady", "noise": "normal", "ramp_in_use": True},
}


@dataclass
class Sim:
    raw: dict
    ops: dict
    scn: dict
    weights: dict
    policy: str                       # option being simulated
    t_decision: int | None = None
    t_exec: int | None = None
    protect: set = field(default_factory=set)
    log: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    caps: dict = field(default_factory=dict)        # capability-minutes per guest
    lost: dict = field(default_factory=dict)


def _transition_min(raw, ops, ship, target, crew, name):
    st = raw["ship"]["state_transitions"]
    t_speed = st["speed_band_change_min"] if target["speed_kn"] != ship["speed_kn"] else 0
    t_quiet = st["go_quiet_min"] if target["noise"] == "quiet" and ship["noise"] != "quiet" else 0
    t_deck = 0
    if ship["deck"] != "clear":
        d = ops["crew_policy"]["deck_clear_min"].get(crew)
        t_deck = 10 ** 6 if d is None else d
    # flight-deck ops need a steady course once aligned into wind (A.3), so they settle too
    settle = st["course_settle_min"] if target["course"] == "steady" or name == "flight_ops" else 0
    return max(t_speed, t_quiet, t_deck) + settle


PROTECT = {"suspend_survey": {"G4"}, "recover_then_resume": {"G3"}, "wait_for_leg_end": {"G3"}}


def simulate(raw, ops, scn, weights, policy, t_decision=None, crew=None, t_exec=None, protect=None):
    """Run the timeline under one D3 policy: 'continue' (no decision), 'wait_for_leg_end',
    'recover_then_resume', 'suspend_survey'. Returns the Sim with log, per-minute rows and capability-minutes."""
    G = loader.load_guest_data(raw)
    d3, d4 = ops["d3"], ops["d4"]
    crew = scn["crew"] if crew is None else crew
    env = dict(scn["environment"])
    ship = dict(scn["initial"])
    ship["posture"] = "survey"
    reserve = ship.pop("reserve_kw")
    cool_cap = loader.cooling_capacity_kw(raw["ship"], env["seawater_c"])
    if ship.get("cooling") == "degraded":
        cool_cap *= raw["ship"]["cooling"]["degraded_factor"]
    H = d3["horizon_min"]
    t_end = (t_decision or 0) + H
    s = Sim(raw, ops, scn, weights, policy, t_decision, t_exec,
            set(PROTECT.get(policy, set()) if protect is None else protect))
    s.caps = {g: 0.0 for g in scn["aboard"]}
    # guest states
    g3 = {"act": scn["guests"]["G3"]["activity"], "leg_len": scn["guests"]["G3"]["leg_min"], "progress": 0,
          "useful": 0, "lost": 0, "charge_left": 0, "legs_done": 0}
    g4 = {"act": scn["guests"]["G4"]["activity"], "battery": scn["guests"]["G4"]["battery_pct"],
          "landing_left": 0, "charge_init_left": 0, "ready": False, "deadline": None, "ditched": False}
    modes = {g: scn["guests"].get(g, {}).get("mode", "full") for g in scn["aboard"]}   # requested D4 modes
    granted = dict(modes)
    target, trans_left, posture_goal = None, 0, None
    requested_at = -1
    shed_stack = []        # D4 actions currently in force (for restore in reverse)
    events = {e["t"]: e for e in scn["timeline"]}
    window_end = None
    resume_planned = False

    def say(t, kind, text, **kw):
        s.log.append({"t": t, "kind": kind, "text": text, **kw})

    def request_posture(t, name, speed):
        nonlocal target, trans_left, posture_goal, requested_at
        requested_at = t
        tgt = dict(POSTURES[name], speed_kn=speed)
        trans_left = _transition_min(raw, ops, ship, tgt, crew, name)
        target, posture_goal = tgt, name
        ship["posture"] = "transit"
        ship["course"], ship["noise"] = "free", "manoeuvring"
        say(t, "ship", f"request {name} posture ({speed} kn, {tgt['course']}, {tgt['noise']}); ready in {trans_left} min (A.6)")

    survey_speed = scn["initial"]["speed_kn"]
    rec_speed = d3["recovery_speed_kn"]
    for t in range(0, t_end + 1):
        # ---- events
        e = events.get(t)
        if e and e["event"] == "battery_report":
            g4["battery"] = e["battery_pct"]
            env["wind_kn"] = e.get("wind_kn", env["wind_kn"])
            em = next(x for x in G["G4"].card["special_events"] if x["type"] == "battery_emergency")
            if g4["battery"] < em["trigger"]["value"]:
                g4["deadline"] = t + em["recovery_deadline_minutes"]
                say(t, "event", f"G4 battery {g4['battery']} % < {em['trigger']['value']} % → must land by min "
                                f"{g4['deadline']} or {em['if_deadline_missed']} (wind {env['wind_kn']} kn)")
        if e and e["event"] == "genset_trip":
            reserve = e["reserve_kw"]
            say(t, "event", f"genset trip → continuous reserve {reserve} kW (A.9)")
            trip_check = True
        # ---- D3 policy execution
        if t == s.t_exec and policy in ("recover_then_resume", "suspend_survey"):
            if g3["act"] == "surveying":
                g3["act"] = "holding"
                say(t, "action", "G3 hold depth (stop listening before the acoustic link breaks)")
            request_posture(t, "flight_ops", rec_speed)
            window_end = (s.t_decision or t) + d3["min_recovery_window_min"]
        # ---- ship transitions
        if t == requested_at:
            pass                                   # the request minute does not count toward A.6 time
        elif target is not None and trans_left == 0 and ship["posture"] == "transit":
            ship.update({k: v for k, v in target.items()})
            ship["posture"] = posture_goal
            say(t, "ship", f"{posture_goal} posture established")
        elif target is not None and ship["posture"] == "transit":
            trans_left -= 1
            if trans_left == 0:
                ship.update({k: v for k, v in target.items()})
                ship["posture"] = posture_goal
                say(t, "ship", f"{posture_goal} posture established")
        # ---- G4
        if g4["act"] == "in_flight":
            if t > 0:
                g4["battery"] = max(0.0, g4["battery"] - d3["battery_drain_pct_per_min"])
            if g4["deadline"] is not None and t >= g4["deadline"]:
                g4["act"], g4["ditched"] = "ditched", True
                say(t, "loss", "G4 ditched: recovery deadline missed")
            elif g4["deadline"] is not None and ship["posture"] == "flight_ops" and \
                    all(_ok(r["operator"], _ship_value(ship, env, r["field"]), r["value"])
                        for r in requirements(G["G4"].card, "launch_recovery") if r["field"] != "navigation.course_keeping"):
                g4["act"], g4["landing_left"] = "landing", d3["landing_min"]
                say(t, "action", f"G4 recovery started (deck clear, {ship['speed_kn']} kn, wind {env['wind_kn']} kn ≤ 25)")
        elif g4["act"] == "landing":
            g4["landing_left"] -= 1
            if g4["landing_left"] <= 0:
                g4["act"] = "charging_initial"
                g4["charge_init_left"] = G["G4"].windows[0]["minutes"]
                say(t, "action", f"G4 landed at min {t} (deadline {g4['deadline']}); charging {G['G4'].windows[0]['total_kw']:g} kW")
        # ---- G3
        if g3["act"] == "holding" and policy == "recover_then_resume" and window_end is not None and t >= window_end \
                and g4["act"] in ("charging_initial", "charging_followup") and not resume_planned:
            request_posture(t, "survey", survey_speed)
            resume_planned = True
        if g3["act"] == "holding" and resume_planned and ship["posture"] == "survey":
            g3["lost"] += g3["progress"]
            say(t, "action", f"G3 resumes: leg re-run from the start ({g3['progress']} min of progress lost)")
            g3["progress"], g3["act"] = 0, "surveying"
        if g3["act"] == "holding" and policy == "suspend_survey" and g4["act"] in ("charging_initial", "charging_followup") \
                and ship["posture"] in ("flight_ops",) and not g3.get("recovering"):
            g3["recovering"] = True
            g3["lost"] += g3["progress"]
            say(t, "action", f"survey suspended: G3 leg abandoned ({g3['progress']} min done, "
                             f"{g3['leg_len'] - g3['progress']} min not flown); vehicle to the ramp")
            g3["progress"] = 0
            request_posture(t, "ramp", rec_speed)
        if g3["act"] == "surveying":
            if ship["posture"] == "survey":
                g3["progress"] += 1
                if g3["progress"] >= g3["leg_len"]:
                    g3["useful"] += g3["progress"]
                    g3["legs_done"] += 1
                    g3["progress"] = 0
                    g3["act"] = "awaiting_recovery"
                    say(t, "action", "G3 leg complete; vehicle to the ramp for recovery and charge")
                    request_posture(t, "ramp", rec_speed)
        if g3["act"] in ("holding", "awaiting_recovery") and ship["posture"] == "ramp" and g4["act"] != "landing":
            g3["act"], g3["ramp_left"] = "ramp_recovery", d3["uuv_ramp_recovery_min"]
        elif g3["act"] == "ramp_recovery":
            g3["ramp_left"] -= 1
            if g3["ramp_left"] <= 0:
                g3["act"] = "charging"
                g3["charge_left"] = G["G3"].windows[0]["minutes"]
                say(t, "action", f"G3 on cradle; non-interruptible charge {G['G3'].windows[0]['total_kw']:g} kW "
                                 f"× {g3['charge_left']} min")
                # survey asset now charging: the ship returns to flight-ops posture so the drone can relaunch
                request_posture(t, "flight_ops", rec_speed)
        # ---- requested electrical loads
        req = {}
        req["G2"] = G["G2"].modes["full"]["kw"]
        req["G5"] = G["G5"].modes["full"]["kw"]
        req["G3"] = {"surveying": G["G3"].modes["full"]["kw"], "holding": G["G3"].modes["full"]["kw"],
                     "awaiting_recovery": G["G3"].modes["full"]["kw"], "ramp_recovery": G["G3"].modes["full"]["kw"],
                     "charging": G["G3"].windows[0]["total_kw"], "cradle": G["G3"].modes["standby"]["kw"]}[g3["act"]]
        req["G4"] = {"in_flight": G["G4"].modes["standby"]["kw"], "landing": G["G4"].modes["standby"]["kw"],
                     "charging_initial": G["G4"].windows[0]["total_kw"], "charging_followup": G["G4"].modes["full"]["kw"],
                     "ditched": G["G4"].modes["standby"]["kw"]}[g4["act"]]
        # protected loads this minute
        prot = set(s.protect)
        if g3["act"] == "charging":
            prot.add("G3")                               # non-interruptible (B G3)
        for g in scn["aboard"]:
            if G[g].safety_critical:
                prot.add(g)
        # ---- D4
        demand = _granted_load(G, req, granted)
        if e and e["event"] == "genset_trip":
            t0 = time.perf_counter()
            order = shed_order(G, req, granted, prot, weights)
            dt = (time.perf_counter() - t0) * 1000
            plan_txt = " → ".join(f"{a['kind']} {a['guest']} {a['from']}→{a['to']} ({a['freed_kw']:g} kW, cost {a['cost']:g})"
                                  for a in order) or "nothing sheddable"
            say(t, "D4", f"declared order (computed in {dt:.1f} ms; protected: {', '.join(sorted(prot)) or 'none'}): {plan_txt}")
            if demand <= min(reserve, cool_cap):
                say(t, "D4", f"demand {demand:.1f} kW ≤ reserve {reserve} kW and cooling {cool_cap:.0f} kW: nothing shed now; "
                             f"order armed for the next load step")
        cap_p = reserve
        if demand > cap_p + 1e-9 or demand > cool_cap + 1e-9:
            t0 = time.perf_counter()
            seq, granted = shed(G, req, granted, prot, weights, min(cap_p, cool_cap))
            dt = time.perf_counter() - t0
            for i, a in enumerate(seq):
                a_t = d4["first_action_s"] + i * d4["step_interval_s"]
                shed_stack.append(a)
                say(t, "D4", f"[+{a_t:.1f} s] {a['text']}", step=a, compute_ms=round(dt * 1000, 2))
            if not seq:
                say(t, "D4", f"overload {demand:.1f} kW > {cap_p} kW but every remaining load is protected")
        elif shed_stack:
            a = shed_stack[-1]
            trial = dict(granted)
            trial[a["guest"]] = a["from"]
            if _granted_load(G, req, trial) + d4["restore_hysteresis_kw"] <= min(cap_p, cool_cap):
                granted = trial
                shed_stack.pop()
                say(t, "D4", f"restore {a['guest']} to {a['from']} (headroom returned)")
        # ---- G4 charge progress only if granted
        if g4["act"] == "charging_initial" and granted["G4"] == "full":
            g4["charge_init_left"] -= 1
            if g4["charge_init_left"] <= 0:
                g4["act"], g4["ready"] = "charging_followup", True
                say(t, "action", "G4 initial charge done; relaunch-ready")
        if g3["act"] == "charging":
            g3["charge_left"] -= 1
            if g3["charge_left"] <= 0:
                g3["act"] = "cradle"
        # ---- capability accounting (scored from the decision onwards)
        load = _granted_load(G, req, granted)
        cap = {}
        cap["G5"] = G["G5"].modes[granted["G5"]]["capability"] if ship["emission"] != "silent" else 0
        probe_ok = all(_ok(r["operator"], _ship_value(ship, env, r["field"]), r["value"])
                       for r in requirements(G["G2"].card, "probe_operation"))
        cap["G2"] = (G["G2"].modes[granted["G2"]]["capability"] if probe_ok else 0)
        cap["G3"] = 1.0 if (g3["act"] == "surveying" and ship["posture"] == "survey") else 0.0
        cap["G4"] = 1.0 if ((g4["act"] == "in_flight" and g4["deadline"] is None) or
                            (g4["ready"] and ship["posture"] == "flight_ops")) else 0.0
        if s.t_decision is not None and s.t_decision <= t < s.t_decision + H:
            for g in s.caps:
                s.caps[g] += cap[g]
        s.rows.append({"t": t, "posture": ship["posture"], "speed_kn": ship["speed_kn"], "reserve_kw": cap_p,
                       "power_kw": round(load, 1), "cooling_kw": round(load, 1), "cooling_cap_kw": round(cool_cap, 1),
                       "G2": granted["G2"], "G3": g3["act"], "G4": g4["act"], "G5": granted["G5"],
                       "g4_battery": round(g4["battery"], 1), "satcom_mbps": G["G5"].data["satcom"] if granted["G5"] != "off" else 0,
                       "acoustic": g3["act"] == "surveying", "los_video": g4["act"] == "in_flight"})
    g3["useful"] += g3["progress"] if g3["act"] == "surveying" else 0
    s.lost = {"G3_progress_lost_min": g3["lost"], "G3_legs_done": g3["legs_done"], "G4_ditched": g4["ditched"],
              "G4_landed": next((x["t"] for x in s.log if x["text"].startswith("G4 landed")), None),
              "G4_deadline": g4["deadline"]}
    return s


def _granted_load(G, req, granted):
    tot = 0.0
    for g, kw in req.items():
        mode = granted.get(g, "full")
        if mode == "full":
            tot += kw
        else:
            tot += G[g].modes[mode]["kw"]
    return tot


def shed_order(G, req, granted, protect, weights):
    """Declared order: every throttle/deferral (cheapest weighted capability per kW first),
    then every shed. Protected guests never appear."""
    steps = []
    for g, kw in req.items():
        if g in protect:
            continue
        cur = granted.get(g, "full")
        cur_kw = kw if cur == "full" else G[g].modes[cur]["kw"]
        cur_cap = G[g].modes[cur]["capability"]
        for role, phase in (("low", 0), ("standby", 0), ("off", 1)):
            if role not in G[g].modes or role == cur:
                continue
            r = G[g].modes[role]
            freed = cur_kw - r["kw"]
            if freed <= 0:
                continue
            cost = weights.get(g, 1) * max(0.0, cur_cap - r["capability"])
            label = "throttle" if role == "low" else ("defer" if role == "standby" else "shed")
            steps.append({"guest": g, "from": cur, "to": role, "freed_kw": freed, "cost": cost, "phase": phase,
                          "kind": label})
    steps.sort(key=lambda a: (a["phase"], a["cost"] / a["freed_kw"], a["guest"]))
    return steps


def shed(G, req, granted, protect, weights, cap):
    granted = dict(granted)
    seq = []
    while _granted_load(G, req, granted) > cap + 1e-9:
        order = shed_order(G, req, granted, protect, weights)
        if not order:
            break
        a = order[0]
        granted[a["guest"]] = a["to"]
        lost_txt = f"loses {a['cost']:g} weighted capability" if a["cost"] else "no capability lost"
        a["text"] = (f"{a['kind']} {a['guest']} {a['from']}→{a['to']} (frees {a['freed_kw']:g} kW, {lost_txt}); "
                     f"load now {_granted_load(G, req, granted):.1f} kW of {cap:g} kW")
        seq.append(a)
    return seq, granted


# ----------------------------------------------------------------------------- D3 decision
OPTIONS = {
    "wait_for_leg_end": "keep surveying; recover the drone when the leg ends",
    "recover_then_resume": "recover the drone now; survey holds depth for the recovery window, then re-runs the leg",
    "suspend_survey": "recover the drone now and keep the ship free to manoeuvre; survey leg abandoned, vehicle recovered",
}


def right_of_way(raw, scn, priority, crew=None):
    """D3 at the first conflict in the timeline. Returns the decision, rationale and every option's score."""
    t_start = time.perf_counter()
    ops = load_ops()
    w = raw["priority"][priority]["weights"]
    crew = scn["crew"] if crew is None else crew
    G = loader.load_guest_data(raw)
    ev = next(e for e in scn["timeline"] if e["event"] == "battery_report")
    t_d = ev["t"]
    conflicts = conflicts_between(G["G3"].card, "surveying", G["G4"].card, "launch_recovery", ops["d3"]["implications"])
    em = next(x for x in G["G4"].card["special_events"] if x["type"] == "battery_emergency")
    deadline = t_d + em["recovery_deadline_minutes"]
    # crew confirmation policy (D5 rule)
    delay = ops["crew_policy"]["confirm_delay_min"].get(crew)
    st = raw["ship"]["state_transitions"]
    reach = max(st["speed_band_change_min"], 0 if scn["initial"]["deck"] == "clear" else
                (ops["crew_policy"]["deck_clear_min"].get(crew) or 10 ** 6)) + st["course_settle_min"] + ops["d3"]["landing_min"]
    if delay is None:
        confirm, t_exec = "automatic (no crew aboard)", t_d
    elif t_d + delay + reach <= deadline:
        confirm, t_exec = f"human confirms (≤{delay} min with {crew} crew)", t_d + delay
    else:
        confirm, t_exec = (f"automatic: waiting {delay} min for {crew}-crew confirmation would land the drone at min "
                           f"{t_d + delay + reach} > deadline {deadline}"), t_d
    results = []
    for name, desc in OPTIONS.items():
        sim = simulate(raw, ops, scn, w, name, t_decision=t_d, crew=crew, t_exec=t_exec)
        H = ops["d3"]["horizon_min"]
        U = sum(w.get(g, 1) * c for g, c in sim.caps.items()) / H
        hard = []
        if sim.lost["G4_ditched"] and not ops["d3"]["allow_asset_loss"]:
            hard.append(f"drone ditches at min {deadline} (battery deadline)")
        results.append({"option": name, "desc": desc, "U": round(U, 3), "feasible": not hard, "violations": hard,
                        "cap_minutes": {g: round(c, 1) for g, c in sim.caps.items()}, "sim": sim})
    feas = [r for r in results if r["feasible"]]
    best = max(feas, key=lambda r: (r["U"], r["option"])) if feas else max(results, key=lambda r: r["U"])
    dt = time.perf_counter() - t_start
    sim = best["sim"]
    rationale, loser_cost = _rationale(best, results, ev, deadline, w, priority, sim, scn, G["G4"].windows[0]["total_kw"])
    return {"t": t_d, "priority": priority, "crew": crew, "conflicts": conflicts, "deadline": deadline,
            "confirmation": confirm, "t_exec": t_exec, "decision": best["option"], "decision_desc": best["desc"],
            "rationale": rationale, "cost_to_loser": loser_cost, "options": results, "elapsed_s": round(dt, 3),
            "within_2s": dt <= raw["ship"]["response_time"]["arbitration_s"], "sim": sim}


def _rationale(best, results, ev, deadline, w, priority, sim, scn, charge_kw):
    by = {r["option"]: r for r in results}
    if not best["feasible"]:
        return (f"No option lands the drone by min {deadline}: drone risk accepted; chose '{best['option']}' "
                f"(highest score {best['U']}) to save what can be saved.",
                f"Drone G4 lost ({'; '.join(best['violations'])}).")
    wait = by["wait_for_leg_end"]
    leg = scn["guests"]["G3"]["leg_min"]
    head = (f"Drone first: battery {ev['battery_pct']} % → must land by min {deadline}; waiting for the leg end "
            f"(min {scn['guests']['G3']['leg_start'] + leg}) would ditch it" if not wait["feasible"] else
            "Waiting for the leg end is safe")
    land = sim.lost["G4_landed"]
    if best["option"] == "recover_then_resume":
        lost = sim.lost["G3_progress_lost_min"]
        resume = next((x["t"] for x in sim.log if x["text"].startswith("G3 resumes")), None)
        why = (f"{head}. With '{priority}' (G3 weight {w.get('G3', 1)} vs G4 {w.get('G4', 1)}) the survey only pauses for "
               f"the recovery window: G3 holds depth, the drone lands at min {land}, the leg restarts at min {resume}.")
        cost = (f"Survey loses {lost} min of leg progress plus {resume - ev['t'] if resume else '—'} min paused; "
                f"the drone stays on deck until the re-run leg ends (relaunch delayed).")
    elif best["option"] == "suspend_survey":
        why = (f"{head}. With '{priority}' (G4 weight {w.get('G4', 1)} vs G3 {w.get('G3', 1)}) the ship is released to "
               f"manoeuvre and the drone's {charge_kw:g} kW charge is protected ahead of everything; drone lands at min {land}.")
        cost = (f"Survey loses the whole leg ({sim.lost['G3_progress_lost_min']} min flown + "
                f"{leg - sim.lost['G3_progress_lost_min']} min not flown), to be re-run later; ocean probe idle "
                f"while the ship is above 5 kn.")
    else:
        why = f"{head}. Survey continues."
        cost = "Drone risk accepted." if sim.lost["G4_ditched"] else "No cost."
    alt = "; ".join(f"{r['option']} U={r['U']}" + ("" if r["feasible"] else f" (rejected: {', '.join(r['violations'])})")
                    for r in results)
    return why + f" Options scored: {alt}.", cost


# ----------------------------------------------------------------------------- report
def loss_summary(d) -> list[str]:
    """What every guest got, from the decision onwards, versus running unhindered for the whole horizon."""
    sim, H = d["sim"], load_ops()["d3"]["horizon_min"]
    out = []
    for g, c in sorted(sim.caps.items()):
        acts = [l["text"] for l in sim.log if l["kind"] == "D4" and f" {g} " in f" {l['text']} " and l["text"].startswith("[")]
        note = f"; D4: {len(acts)} action(s)" if acts else ""
        out.append(f"{g}: capability {c:.0f}/{H} min ({100 * c / H:.0f} %){note}")
    if sim.lost.get("G4_ditched"):
        out.append("G4: vehicle lost (ditched)")
    out.append(f"G3: {sim.lost['G3_progress_lost_min']} min of leg progress discarded; {sim.lost['G3_legs_done']} leg(s) completed")
    return out


def print_b(d, out=None):
    import sys
    p = lambda *a: print(*a, file=out or sys.stdout)
    p(f"\n=== Scenario B · priority '{d['priority']}' · crew {d['crew']} ===")
    p(f"D3 at min {d['t']} ({d['elapsed_s']} s; ceiling 2 s): {d['decision']} — {d['decision_desc']}")
    p("Conflict as ship-state conditions:")
    for c in d["conflicts"]:
        p(f"  - {c}")
    p(f"Confirmation (D5 rule): {d['confirmation']}")
    p(f"Rationale: {d['rationale']}")
    p(f"Cost to the loser: {d['cost_to_loser']}")
    p("Options (U = Σ weight × capability-minutes / horizon):")
    for o in d["options"]:
        p(f"  - {o['option']:<20} U={o['U']:<7} {'feasible' if o['feasible'] else 'REJECTED: ' + '; '.join(o['violations'])}"
          f"   cap-min {o['cap_minutes']}")
    p("Timeline:")
    for l in d["sim"].log:
        p(f"  min {l['t']:>3}  {l['kind']:<6} {l['text']}")
    p("What every guest got (from the decision on):")
    for x in loss_summary(d):
        p(f"  - {x}")
    p("Gauges (every 4 min): min posture power/reserve kW  cooling/cap kW  G2 G3 G4 G5  battery")
    for r in d["sim"].rows[::4]:
        p(f"  {r['t']:>3} {r['posture']:<10} {r['power_kw']:>6}/{r['reserve_kw']:<4} {r['cooling_kw']:>6}/{r['cooling_cap_kw']:<6} "
          f"{r['G2']:<8} {r['G3']:<17} {r['G4']:<17} {r['G5']:<5} {r['g4_battery']}")
