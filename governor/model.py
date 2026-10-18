"""D1/D2 optimization model (OR-Tools CP-SAT).

Structure and names follow Whole_model.docx §4–§8:
    decision variables  installed[i], mode_selected[i,m], position_selected[i,p],
                        power_line_selected[i,l], action_selected (removal / relocation / interlock)
    objective           max U = Σ w_i c_im x_im   (then robustness, disruption, rules, margin, placement)
    constraints         add_mode_constraints … add_mission_envelope_constraints

Deviation from the docx (documented in docs/DESIGN_DECISIONS.md):
  * operating modes are chosen separately for the normal envelope and for each degraded state, so
    "holds with one genset down" is answered by the same model (D4 shedding is allowed there,
    never below a safety-critical floor or a non-interruptible charge already running);
  * sustained windows (winch, charges) are modelled as load cases: every combination of windows
    that can coincide must fit, unless the governor adds an interlock ("not at the same time").

Every capacity group is guarded by an assumption literal so that, when a request is infeasible,
the solver names the binding resource classes (minimal core) instead of answering "no".
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

KW = 10          # 0.1 kW resolution
UT = 1000        # utility resolution
ROLES = ("full", "low", "standby", "off")
ACTIVE_ROLES = ("full", "low")      # roles that use data links and compute

GROUPS = ["power_normal", "cooling_normal", "power_line", "power_degraded", "cooling_degraded",
          "mass", "stability", "deck_space", "mast", "hangar", "satcom", "backbone", "los_radio",
          "compute", "installation_time"]


@dataclass
class Problem:
    guests: dict                      # gid -> Guest (only guests in play)
    weights: dict                     # gid -> mission weight
    budget: dict
    installed: dict                   # gid -> current config id, or None (free placement)
    candidate: str | None = None
    allow_removal: bool = True
    allow_relocation: bool = True
    baseline: bool = False            # "admit without touching anyone": all FULL, no interlocks
    disabled_groups: set = field(default_factory=set)
    degraded: list | None = None      # override budget["degraded"] (used for stress tests)
    fixed: dict | None = None         # fix a previous plan's installation/placement (stress tests)
    no_goods: list = field(default_factory=list)
    force_config: dict = field(default_factory=dict)   # {gid: config id} — used to test rejected placements
    time_limit_s: float = 10.0
    seed: int = 42


class Built:
    pass


def generate_candidates(p: Problem) -> dict:
    """Placement configurations each guest may use (card configs minus statically impossible ones)."""
    out = {}
    for gid, g in p.guests.items():
        usable = [c for c in g.configs if not c.issues]
        cur = p.installed.get(gid)
        if p.fixed:
            usable = [c for c in usable if c.id == p.fixed["config"].get(gid)]
        elif cur and (p.baseline or not p.allow_relocation):
            usable = [c for c in usable if c.id == cur]
        if gid in p.force_config:
            usable = [c for c in usable if c.id == p.force_config[gid]]
        out[gid] = usable
    return out


def build_model(p: Problem) -> Built:
    b = Built()
    m = cp_model.CpModel()
    b.m, b.p = m, p
    b.lit = {grp: m.NewBoolVar(f"limit_{grp}") for grp in GROUPS}
    b.cands = generate_candidates(p)
    add_mode_constraints(b)
    add_placement_constraints(b)
    add_power_constraints(b)
    add_cooling_constraints(b)
    add_mission_envelope_constraints(b)
    add_mass_constraints(b)
    add_data_constraints(b)
    add_compute_constraints(b)
    add_time_constraints(b)
    add_installation_constraints(b)
    add_operational_constraints(b)
    add_ship_state_constraints(b)
    add_objectives(b)
    for grp in GROUPS:
        if grp in p.disabled_groups:
            m.Add(b.lit[grp] == 0)
    m.AddAssumptions([b.lit[g] for g in GROUPS if g not in p.disabled_groups])
    return b


def _g(b, grp):
    return b.lit[grp]


# ----------------------------------------------------------------------------- modes / installation
def add_mode_constraints(b):
    m, p = b.m, b.p
    b.inst, b.mn, b.md, b.removed = {}, {}, {}, {}
    scen = p.degraded if p.degraded is not None else p.budget["degraded"]
    b.scen = scen
    for gid, g in p.guests.items():
        v = m.NewBoolVar(f"installed_{gid}")
        b.inst[gid] = v
        if gid == p.candidate:
            m.Add(v == 1)                                        # docx §6: the request must be modelled
        elif gid in p.installed:
            if p.fixed is not None:
                m.Add(v == int(p.fixed["installed"].get(gid, 1)))
            elif p.baseline or not p.allow_removal or g.safety_critical:
                m.Add(v == 1)                                    # safety-critical: never removed automatically
        else:
            m.Add(v == 0)
        b.removed[gid] = None
        if gid in p.installed and gid != p.candidate:
            r = m.NewBoolVar(f"removed_{gid}")
            m.Add(r == 1 - v)
            b.removed[gid] = r
        # normal-envelope mode
        b.mn[gid] = {}
        for role in g.modes:
            b.mn[gid][role] = m.NewBoolVar(f"mode_n_{gid}_{role}")
        m.Add(sum(b.mn[gid].values()) == v)
        if gid == p.candidate:
            # admitting a guest only to park it in standby/off is a refusal in disguise
            m.Add(sum(b.mn[gid][r] for r in ACTIVE_ROLES if r in b.mn[gid]) == 1)
        if p.baseline and gid in p.installed or (p.baseline and gid == p.candidate):
            m.Add(b.mn[gid]["full"] == v)
        if p.fixed and "mode_n" in p.fixed and gid in p.fixed["mode_n"]:
            role = p.fixed["mode_n"][gid]
            if role in b.mn[gid]:
                m.Add(b.mn[gid][role] == v)
        # degraded-state modes (one set per degraded scenario)
        b.md[gid] = {}
        for s in scen:
            b.md[gid][s["name"]] = {role: m.NewBoolVar(f"mode_d_{s['name']}_{gid}_{role}") for role in g.modes}
            m.Add(sum(b.md[gid][s["name"]].values()) == v)
            # a fault never gives a guest more than its normal mode (D4 only throttles or sheds)
            for rd, xd in b.md[gid][s["name"]].items():
                allowed = [b.mn[gid][rn] for rn in g.modes if g.modes[rn]["kw"] >= g.modes[rd]["kw"] - 1e-9]
                m.Add(xd <= sum(allowed))
    # windows
    b.windows = [w for g in p.guests.values() for w in g.windows]
    b.wd = {}
    for s in scen:
        for w in b.windows:
            gid = w["guest"]
            x = m.NewBoolVar(f"win_d_{s['name']}_{w['id']}")
            m.AddImplication(x, b.md[gid][s["name"]]["full"])
            if not w["interruptible"]:
                # a non-interruptible charge may already be running when the fault hits
                m.Add(x == b.mn[gid]["full"])
            b.wd[(s["name"], w["id"])] = x
    # interlocks between windows of different guests (governor operating rules)
    b.interlock = {}
    for w1, w2 in itertools.combinations(b.windows, 2):
        if w1["guest"] == w2["guest"]:
            continue
        il = m.NewBoolVar(f"interlock_{w1['id']}_{w2['id']}")
        if p.baseline:
            m.Add(il == 0)
        both = m.NewBoolVar("")
        m.AddBoolAnd([b.mn[w1["guest"]]["full"], b.mn[w2["guest"]]["full"]]).OnlyEnforceIf(both)
        m.AddImplication(il, both)       # only interlock windows that both exist
        b.interlock[(w1["id"], w2["id"])] = il


def _load_expr(b, gid, modes_vars, role_kw_filter=None):
    g = b.p.guests[gid]
    return sum(int(round(g.modes[r]["kw"] * KW)) * x for r, x in modes_vars.items())


# ----------------------------------------------------------------------------- placement (D2)
def add_placement_constraints(b):
    m, p, bud = b.m, b.p, b.p.budget
    b.cfg = {}
    for gid, g in p.guests.items():
        b.cfg[gid] = {c.id: m.NewBoolVar(f"position_{gid}_{c.id}") for c in b.cands[gid]}
        m.Add(sum(b.cfg[gid].values()) == b.inst[gid])
    b.relocated = {}
    for gid, cur in p.installed.items():
        if gid not in p.guests or cur is None or gid == p.candidate:
            continue
        r = m.NewBoolVar(f"relocated_{gid}")
        same = b.cfg[gid].get(cur)
        if same is None:
            m.Add(r == b.inst[gid])
        else:
            m.Add(r == b.inst[gid] - same)
        b.relocated[gid] = r

    def occ(loc, attr):
        terms = []
        for gid in p.guests:
            for c in b.cands[gid]:
                for a in c.assignments:
                    if a["location"] == loc:
                        terms.append((attr(a), b.cfg[gid][c.id], gid, c))
        return terms

    g_deck = _g(b, "deck_space")
    for bay in ("bay1", "bay2"):
        halves = occ(bay, lambda a: int(round(a["fraction"] * 2)))
        if halves:
            m.Add(sum(h * x for h, x, _, _ in halves) <= int(round(bud[f"{bay}_fraction"] * 2))).OnlyEnforceIf(g_deck)
            mass = occ(bay, lambda a: int(round(a["mass_kg"])))
            cap = int(round(p.budget[f"{bay}_max_kg"]))
            m.Add(sum(k * x for k, x, _, _ in mass) <= cap).OnlyEnforceIf(g_deck)
            # A.3: Bay 1 hosts two 10-ft guests only if neither needs the bay clear
            for h, x, gid, c in halves:
                if h == 1 and p.guests[gid].needs_bay_clear:
                    others = [(h2, x2) for h2, x2, gid2, _ in halves if gid2 != gid]
                    if others:
                        m.Add(sum(h2 * x2 for h2, x2 in others) == 0).OnlyEnforceIf([x, g_deck])
    mast = occ("mast_slot", lambda a: 1)
    if mast:
        m.Add(sum(x for _, x, _, _ in mast) <= int(bud["mast_free"])).OnlyEnforceIf(_g(b, "mast"))
    hangar = occ("flight_deck_hangar", lambda a: 1)
    hangar_guests = {}
    for _, x, gid, c in hangar:
        hangar_guests.setdefault(gid, set()).add(c.id)
    if hangar_guests:
        m.Add(sum(sum(b.cfg[gid][cid] for cid in cids) for gid, cids in hangar_guests.items()) <= int(bud["hangar_capacity"]))\
            .OnlyEnforceIf(_g(b, "hangar"))
    roof = occ("hangar_roof", lambda a: 1)
    if roof:
        m.Add(sum(x for _, x, _, _ in roof) <= int(bud["roof_capacity"])).OnlyEnforceIf(_g(b, "hangar"))
        # optional rule: the roof only exists once a guest holds the flight-deck hangar
        if bud["roof_requires_hangar_guest"]:
            hangar_vars = [b.cfg[gid][cid] for gid, cids in hangar_guests.items() for cid in cids]
            for _, x, _, _ in roof:
                if hangar_vars:
                    m.AddBoolOr(hangar_vars).OnlyEnforceIf(x)
                else:
                    m.Add(x == 0)
    # power_line_selected[i,l]: follows from the position, because ship wiring fixes the line of each
    # connection point (A.1; mapping in config/ship.yaml power.wiring). Exact, no big-M.
    lines = bud["lines"]
    b.line_of_point = dict(bud["wiring"])
    b.on_line = {}
    for gid in p.guests:
        for l in lines:
            zs = [b.cfg[gid][c.id] for c in b.cands[gid] if bud["wiring"].get(c.point) == l]
            v = m.NewBoolVar(f"power_line_selected_{gid}_{l}")
            m.Add(v == sum(zs)) if zs else m.Add(v == 0)
            b.on_line[(gid, l)] = v


# ----------------------------------------------------------------------------- power & cooling
def _window_subsets(b):
    ws = b.windows
    subs = []
    for k in range(0, len(ws) + 1):
        for S in itertools.combinations(ws, k):
            subs.append(S)
    return subs


def _interlocks_in(b, S):
    out = []
    for w1, w2 in itertools.combinations(S, 2):
        key = (w1["id"], w2["id"]) if (w1["id"], w2["id"]) in b.interlock else (w2["id"], w1["id"])
        if key in b.interlock:
            out.append(b.interlock[key])
    return out


def _case_load(b, S, chilled_only=False, gids=None):
    p = b.p
    terms = []
    for gid, g in p.guests.items():
        if gids is not None and gid not in gids:
            continue
        if chilled_only and not g.chilled:
            continue
        terms.append(_load_expr(b, gid, b.mn[gid]))
    for w in S:
        g = p.guests[w["guest"]]
        if chilled_only and not g.chilled:
            continue
        if gids is not None and w["guest"] not in gids:
            continue
        terms.append(int(round(w["delta_kw"] * KW)) * b.mn[w["guest"]]["full"])
    return sum(terms)


def add_power_constraints(b):
    """Normal envelope: every combination of sustained windows that can coincide must fit the
    lowest continuous reserve of the envelope speed bands, unless an interlock forbids it."""
    m, p, bud = b.m, b.p, b.p.budget
    cap = int(round(bud["power_kw"] * KW))
    b.worst_power = m.NewIntVar(0, 10 ** 6, "worst_power_normal")
    b.cases = _window_subsets(b)
    for S in b.cases:
        enf = [il.Not() for il in _interlocks_in(b, S)]
        load = _case_load(b, S)
        m.Add(load <= cap).OnlyEnforceIf(enf + [_g(b, "power_normal")])
        m.Add(b.worst_power >= load).OnlyEnforceIf(enf)
    # power lines (A.1): a line can saturate while the total does not. Exact products
    # y = mode ∧ on_line keep the formulation tight.
    lcap = int(round(bud["line_kw"] * KW))
    b.y_n = {}
    for gid, g in p.guests.items():
        for l in bud["lines"]:
            for r, x in b.mn[gid].items():
                b.y_n[(gid, r, l)] = _and(m, x, b.on_line[(gid, l)])
    for S in b.cases:
        enf = [il.Not() for il in _interlocks_in(b, S)]
        for l in bud["lines"]:
            load = sum(int(round(p.guests[gid].modes[r]["kw"] * KW)) * b.y_n[(gid, r, l)]
                       for gid in p.guests for r in p.guests[gid].modes)
            load += sum(int(round(w["delta_kw"] * KW)) * b.y_n[(w["guest"], "full", l)] for w in S)
            m.Add(load <= lcap).OnlyEnforceIf(enf + [_g(b, "power_line")])
    # peaks: no card declares a ≤60 s peak (all "peak": null), so the +250 kW peak budget and the
    # cooling inertia (+30 kW/60 s) are never needed. Sustained draws are not peaks (A.1).


def add_cooling_constraints(b):
    """Heat = electrical kW at 1:1 (A.2) for chilled-water guests; mast guests are air-cooled."""
    m, bud = b.m, b.p.budget
    cap = int(round(bud["cooling_kw"] * KW))
    b.worst_cool = m.NewIntVar(0, 10 ** 6, "worst_cooling_normal")
    for S in b.cases:
        enf = [il.Not() for il in _interlocks_in(b, S)]
        load = _case_load(b, S, chilled_only=True)
        m.Add(load <= cap).OnlyEnforceIf(enf + [_g(b, "cooling_normal")])
        m.Add(b.worst_cool >= load).OnlyEnforceIf(enf)


def add_mission_envelope_constraints(b):
    """Degraded states of the envelope (A.9/A.10). The governor may throttle or shed (D4), but a
    safety-critical guest never drops below its safe floor and a running non-interruptible charge
    keeps drawing."""
    m, p, bud = b.m, b.p, b.p.budget
    b.deg_power, b.deg_cool = {}, {}
    for s in b.scen:
        name = s["name"]
        pw = []
        cl = []
        for gid, g in p.guests.items():
            e = sum(int(round(g.modes[r]["kw"] * KW)) * x for r, x in b.md[gid][name].items())
            ws = sum(int(round(w["delta_kw"] * KW)) * b.wd[(name, w["id"])] for w in g.windows)
            pw.append(e + ws)
            if g.chilled:
                cl.append(e + ws)
            # line loss stress (A.9 option)
            if s.get("lost_line") not in (None, "none"):
                m.Add(e + ws == 0).OnlyEnforceIf([b.on_line[(gid, s["lost_line"])], _g(b, "power_degraded")])
        pv = m.NewIntVar(0, 10 ** 6, f"power_d_{name}")
        cv = m.NewIntVar(0, 10 ** 6, f"cool_d_{name}")
        m.Add(pv == sum(pw))
        m.Add(cv == sum(cl))
        m.Add(pv <= int(round(s["power_kw"] * KW))).OnlyEnforceIf(_g(b, "power_degraded"))
        m.Add(cv <= int(round(s["cooling_kw"] * KW))).OnlyEnforceIf(_g(b, "cooling_degraded"))
        b.deg_power[name], b.deg_cool[name] = pv, cv
        lcap = int(round(bud["line_kw"] * KW))
        for l in bud["lines"]:
            terms = []
            for gid, g in p.guests.items():
                for r, x in b.md[gid][name].items():
                    terms.append(int(round(g.modes[r]["kw"] * KW)) * _and(m, x, b.on_line[(gid, l)]))
                for w in g.windows:
                    terms.append(int(round(w["delta_kw"] * KW)) * _and(m, b.wd[(name, w["id"])], b.on_line[(gid, l)]))
            m.Add(sum(terms) <= lcap).OnlyEnforceIf(_g(b, "power_line"))


def _and(m, a, c):
    y = m.NewBoolVar("")
    m.AddImplication(y, a)
    m.AddImplication(y, c)
    m.AddBoolOr([a.Not(), c.Not(), y])
    return y


# ----------------------------------------------------------------------------- mass, data, compute
def add_mass_constraints(b):
    m, p, bud = b.m, b.p, b.p.budget
    m.Add(sum(int(round(g.mass_kg)) * b.inst[gid] for gid, g in p.guests.items())
          <= int(bud["mass_kg"])).OnlyEnforceIf(_g(b, "mass"))
    b.stab = sum(int(round(c.stability_kg_eq * 10)) * b.cfg[gid][c.id]
                 for gid in p.guests for c in b.cands[gid])
    m.Add(b.stab <= int(bud["stability_kg_eq"] * 10)).OnlyEnforceIf(_g(b, "stability"))


def _active(b, gid):
    return sum(b.mn[gid][r] for r in ACTIVE_ROLES if r in b.mn[gid])


def add_data_constraints(b):
    m, p, bud = b.m, b.p, b.p.budget
    for key, grp in (("satcom", "satcom"), ("backbone", "backbone"), ("los_radio", "los_radio")):
        m.Add(sum(int(round(g.data.get(key, 0) * 100)) * _active(b, gid) for gid, g in p.guests.items())
              <= int(round(bud[f"{key}_mbps"] * 100))).OnlyEnforceIf(_g(b, grp))


def add_compute_constraints(b):
    m, p, bud = b.m, b.p, b.p.budget
    for key in ("cpu_cores", "ram_gb", "accelerator_units", "storage_gb"):
        m.Add(sum(int(round(float(g.compute.get(key) or 0) * 10)) * _active(b, gid)
                  for gid, g in p.guests.items()) <= int(round(bud[key] * 10))).OnlyEnforceIf(_g(b, "compute"))


def add_time_constraints(b):
    """Port-call crane time: install the candidate + remove/relocate others within the window.
    (Response-time ceilings are enforced on the solver itself — see solve_model.)"""
    m, p, bud = b.m, b.p, b.p.budget
    terms = []
    if p.candidate and p.candidate not in p.installed:
        terms.append(int(round(p.guests[p.candidate].install_port_minutes)))
    for gid, r in b.removed.items():
        if r is not None:
            terms.append(int(round(p.guests[gid].install_port_minutes * bud["removal_factor"])) * r)
    for gid, r in b.relocated.items():
        terms.append(int(round(p.guests[gid].install_port_minutes * (1 + bud["removal_factor"]))) * r)
    if terms:
        m.Add(sum(terms) <= int(bud["port_window_min"])).OnlyEnforceIf(_g(b, "installation_time"))


def add_installation_constraints(b):
    """At sea, nothing physical changes (handled by the classifier before the model is built:
    it fixes installation and placement). In port everything may change (A.11)."""
    return


def add_operational_constraints(b):
    """requires / excludes / part_of (B.0). part_of is implicit: one installed[] per assembly."""
    m, p = b.m, b.p
    for gid, g in p.guests.items():
        for ex in g.excludes:
            if ex.get("type") == "absolute" and ex.get("other_guest") in p.guests:
                m.Add(b.inst[gid] + b.inst[ex["other_guest"]] <= 1)
        for rq in g.requires:
            if rq.get("type") == "guest" and rq.get("guest") in p.guests:
                m.AddImplication(b.inst[gid], b.inst[rq["guest"]])


def add_ship_state_constraints(b):
    """Ship-state conditions (A.6) never make admission infeasible by themselves: conflicting
    conditions between guests become standing operating rules (reported), and whether each mode
    can ever run inside the envelope is reported by explain.envelope_operability()."""
    return


# ----------------------------------------------------------------------------- objectives
def add_objectives(b):
    m, p, bud = b.m, b.p, b.p.budget
    b.U_n = sum(int(round(p.weights.get(gid, 1) * g.modes[r]["capability"] * UT)) * x
                for gid, g in p.guests.items() for r, x in b.mn[gid].items())
    ud = []
    for s in b.scen:
        name = s["name"]
        for gid, g in p.guests.items():
            w = p.weights.get(gid, 1)
            for r, x in b.md[gid][name].items():
                if r == "full" and g.windows:
                    # interruptible window deferred in the degraded state costs capability
                    for win in g.windows:
                        if win["interruptible"]:
                            dc = win["defer_capability"]
                            ud.append(int(round(w * dc * UT)) * x)
                            ud.append(int(round(w * (1 - dc) * UT)) * b.wd[(name, win["id"])])
                            break
                    else:
                        ud.append(int(round(w * UT)) * x)
                else:
                    ud.append(int(round(w * g.modes[r]["capability"] * UT)) * x)
    b.U_d = sum(ud) if ud else 0
    b.n_interlocks = sum(b.interlock.values()) if b.interlock else 0
    disr = []
    for gid, r in b.removed.items():
        if r is not None:
            disr.append(int(round(p.guests[gid].install_port_minutes)) * r)
    for gid, r in b.relocated.items():
        disr.append(int(round(p.guests[gid].install_port_minutes * 2)) * r)
    b.disruption = sum(disr) if disr else 0
    # margin index: free share (per-mille) of the tightest resource
    def frac(name, used, cap):
        v = m.NewIntVar(-10 ** 7, 1000, f"margin_{name}")
        m.Add(v * cap <= (cap - used) * 1000)
        return v
    margins = [frac("power_normal", b.worst_power, int(round(bud["power_kw"] * KW))),
               frac("cooling_normal", b.worst_cool, int(round(bud["cooling_kw"] * KW))),
               frac("mass", sum(int(round(g.mass_kg)) * b.inst[gid] for gid, g in p.guests.items()), int(bud["mass_kg"])),
               frac("stability", b.stab, int(bud["stability_kg_eq"] * 10))]
    for s in b.scen:
        margins.append(frac(f"power_{s['name']}", b.deg_power[s["name"]], int(round(s["power_kw"] * KW))))
    b.MI = m.NewIntVar(-10 ** 7, 1000, "MI")
    m.AddMinEquality(b.MI, margins)
    # D2: preferred placement + keep space for future guests
    pref = sum(b.cfg[gid][c.id] for gid in p.guests for c in b.cands[gid] if c.preferred)
    b.placement_score = pref
    # no-goods (alternatives)
    for ng in p.no_goods:
        lits = []
        for (kind, key), val in ng.items():
            var = _sig_var(b, kind, key)
            if var is None:
                continue
            lits.append(var.Not() if val else var)
        if lits:
            m.AddBoolOr(lits)


def _sig_var(b, kind, key):
    if kind == "removed":
        return b.removed.get(key)
    if kind == "relocated":
        return b.relocated.get(key)
    if kind == "mode_n":
        gid, role = key
        return b.mn.get(gid, {}).get(role)
    if kind == "interlock":
        return b.interlock.get(key)
    return None


# ----------------------------------------------------------------------------- solve
OBJECTIVES = [("U_normal", "U_n", 1), ("U_degraded", "U_d", 1), ("disruption", "disruption", -1),
              ("interlocks", "n_interlocks", -1), ("margin_index", "MI", 1), ("placement", "placement_score", 1)]


def _solver(p):
    s = cp_model.CpSolver()
    s.parameters.num_workers = 1                 # deterministic, replayable
    s.parameters.random_seed = p.seed
    s.parameters.max_time_in_seconds = p.time_limit_s
    return s


def solve_model(p: Problem, lexicographic: bool = True):
    """Lexicographic: U_normal → U_degraded → −disruption → −interlocks → margin → placement."""
    b = build_model(p)
    s = _solver(p)
    status = None
    b.all_optimal = True
    n_vars = len(b.m.Proto().variables)
    for name, attr, sign in (OBJECTIVES if lexicographic else OBJECTIVES[:1]):
        expr = getattr(b, attr)
        if isinstance(expr, int):
            continue
        b.m.Maximize(expr) if sign > 0 else b.m.Minimize(expr)
        status = s.Solve(b.m)
        if status == cp_model.INFEASIBLE:
            core = s.SufficientAssumptionsForInfeasibility()
            names = [g for g in GROUPS if b.lit[g].Index() in core]
            return None, binding_groups(p, names)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, ["solver_timeout"]
        if status != cp_model.OPTIMAL:
            b.all_optimal = False
        val = int(round(s.ObjectiveValue()))
        b.m.Add(expr >= val) if sign > 0 else b.m.Add(expr <= val)
        # warm start the next stage from this solution
        b.m.ClearHints()
        for i in range(n_vars):
            v = b.m.GetIntVarFromProtoIndex(i)
            b.m.AddHint(v, s.Value(v))
    return extract(b, s), []


def feasible(p: Problem, groups: list[str]) -> bool:
    b = build_model(p)
    b.m.ClearAssumptions()
    for g in GROUPS:
        b.m.Add(b.lit[g] == (1 if g in groups else 0))
    st = _solver(p).Solve(b.m)
    return st in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def binding_groups(p: Problem, core: list[str]) -> list[str]:
    """Every resource class that alone makes the request infeasible; if none does on its own,
    the minimal combination that does (minimal core)."""
    singles = [g for g in GROUPS if g not in p.disabled_groups and not feasible(p, [g])]
    return singles or minimal_core(p, core)


def minimal_core(p: Problem, core: list[str]) -> list[str]:
    """Deletion filter: keep only limits whose removal makes the request feasible."""
    keep = list(core)
    for g in list(keep):
        trial = [k for k in keep if k != g]
        if trial and not feasible(p, trial):
            keep = trial
    return keep


def extract(b, s) -> dict:
    p = b.p
    plan = {"installed": {}, "config": {}, "mode_n": {}, "mode_d": {}, "windows_d": {},
            "interlocks": [], "lines": {}, "removed": [], "relocated": []}
    for gid in p.guests:
        inst = bool(s.Value(b.inst[gid]))
        plan["installed"][gid] = inst
        if not inst:
            continue
        plan["config"][gid] = next(cid for cid, v in b.cfg[gid].items() if s.Value(v))
        plan["mode_n"][gid] = next(r for r, v in b.mn[gid].items() if s.Value(v))
        plan["mode_d"][gid] = {sn: next(r for r, v in md.items() if s.Value(v)) for sn, md in b.md[gid].items()}
    for (sn, wid), v in b.wd.items():
        plan["windows_d"].setdefault(sn, {})[wid] = bool(s.Value(v))
    plan["interlocks"] = [k for k, v in b.interlock.items() if s.Value(v)]
    plan["lines"] = dict(b.line_of_point)
    plan["optimal"] = getattr(b, "all_optimal", True)
    plan["removed"] = [gid for gid, r in b.removed.items() if r is not None and s.Value(r)]
    plan["relocated"] = [gid for gid, r in b.relocated.items() if s.Value(r)]
    plan["objective"] = {"U_normal": s.Value(b.U_n) / UT, "U_degraded": (s.Value(b.U_d) / UT) if not isinstance(b.U_d, int) else 0,
                         "disruption_min": s.Value(b.disruption) if not isinstance(b.disruption, int) else 0,
                         "interlocks": len(plan["interlocks"]), "MI_pct": s.Value(b.MI) / 10}
    plan["scenarios"] = [sc["name"] for sc in b.scen]
    return plan


def signature(plan: dict, p: Problem) -> dict:
    sig = {}
    for gid in p.installed:
        if gid in p.guests and gid != p.candidate:
            sig[("removed", gid)] = gid in plan["removed"]
            sig[("relocated", gid)] = gid in plan["relocated"]
    for gid, g in p.guests.items():
        for role in g.modes:
            if role != "full":
                sig[("mode_n", (gid, role))] = plan["mode_n"].get(gid) == role
    for k in _all_interlock_keys(p):
        sig[("interlock", k)] = k in plan["interlocks"]
    return sig


def _all_interlock_keys(p):
    ws = [w for g in p.guests.values() for w in g.windows]
    return [(a["id"], c["id"]) for a, c in itertools.combinations(ws, 2) if a["guest"] != c["guest"]]
