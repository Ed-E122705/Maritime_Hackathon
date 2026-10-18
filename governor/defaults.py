"""Default-combination search: which three guests should already be aboard in Scenario A?

For every mission priority file and every 3-guest set:
  1. place the set optimally in port (D2) with every guest kept aboard;
  2. score what the ship delivers: normal-envelope utility, degraded utility, tightest margin;
  3. present every remaining card as the jury card and record the D1 verdict and the utility after
     admission (the "output" the ship would have after the jury's request).
"""
from __future__ import annotations

import itertools

from . import loader
from .admission import classify_admission, evaluate
from .model import Problem, solve_model


def place_set(raw, guests, trio, priority):
    budget = loader.load_ship_budget(raw)
    p = Problem(guests={g: guests[g] for g in trio}, weights=raw["priority"][priority]["weights"],
                budget=budget, installed={g: None for g in trio}, candidate=None, allow_removal=False)
    plan, core = solve_model(p)
    return plan, core, budget


def search_defaults(raw, priorities=None, pool=None, size=3, judge_candidates=True):
    guests = loader.load_guest_data(raw)
    pool = pool or sorted(guests)
    priorities = priorities or sorted(raw["priority"])
    rows = []
    for pr in priorities:
        w = raw["priority"][pr]["weights"]
        for trio in itertools.combinations(pool, size):
            plan, core, budget = place_set(raw, guests, trio, pr)
            row = {"priority": pr, "set": list(trio)}
            if plan is None:
                row.update(feasible=False, binding=core)
                rows.append(row)
                continue
            ev = evaluate(plan, guests, budget)
            full_util = sum(w.get(g, 1) for g in trio)
            row.update(feasible=True, U_normal=plan["objective"]["U_normal"], U_max=full_util,
                       U_degraded=plan["objective"]["U_degraded"], MI_pct=plan["objective"]["MI_pct"],
                       all_full=all(plan["mode_n"][g] == "full" for g in trio),
                       interlocks=plan["interlocks"], placement=plan["config"],
                       mass_t=round(ev["mass_kg"] / 1000, 3), power_worst_kw=ev["power_n"],
                       cooling_worst_kw=ev["cool_n"])
            if judge_candidates:
                jury = {}
                for c in pool:
                    if c in trio:
                        continue
                    scn = {"installed": dict(plan["config"]), "candidate": c}
                    r = classify_admission(raw, scn, pr, n_alternatives=0)
                    u_after = r["plan"]["objective"]["U_normal"] if r.get("plan") else row["U_normal"]
                    jury[c] = {"verdict": r["verdict"], "U_after": u_after,
                               "actions": [a["text"] for a in r.get("actions", [])],
                               "binding": r.get("binding", [])}
                row["jury"] = jury
                row["U_after_mean"] = round(sum(j["U_after"] for j in jury.values()) / max(1, len(jury)), 3)
                row["admitted"] = sum(1 for j in jury.values() if j["verdict"] in ("YES", "YES-IF"))
                row["verdict_mix"] = sorted({j["verdict"] for j in jury.values()})
            rows.append(row)
    return rows


def rank(rows, priority):
    """Feasible sets with every guest at full power first; then normal utility, degraded utility,
    expected utility after the jury card, tightest margin."""
    cand = [r for r in rows if r["priority"] == priority and r.get("feasible")]
    cand.sort(key=lambda r: (not r["all_full"], -r["U_normal"], -r["U_degraded"],
                             -r.get("U_after_mean", 0), -r["MI_pct"]))
    return cand
