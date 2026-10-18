"""Resource Governor dashboard — a thin Flask layer over the existing engine.

Nothing here decides anything: every number comes from governor.admission (A, A′),
governor.rightofway (B) and governor.defaults (proposed starting sets). Jury knobs become
in-memory overrides (loader.apply_overrides), exactly like `--set` on the CLI.

    make dashboard          # → http://127.0.0.1:5050
"""
from __future__ import annotations

import copy
import json
import sys
import time
from functools import lru_cache
from pathlib import Path

from flask import Flask, jsonify, render_template, request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from governor import loader                                         # noqa: E402
from governor.admission import (_usage_table, build_problem,         # noqa: E402
                                classify_admission, evaluate)
from governor.defaults import rank, search_defaults                  # noqa: E402
from governor.model import solve_model                               # noqa: E402
from governor.rightofway import right_of_way                         # noqa: E402

app = Flask(__name__)
RAW = loader.load_raw()
SCN = {p.stem: p for p in sorted((ROOT / "scenarios").glob("*.yaml"))}


def _json(obj):
    """Engine results hold dataclasses/sets; make them JSON-safe the same way the CLI does."""
    return json.loads(json.dumps(obj, default=str))


def _raw_with(overrides):
    ov = [o.strip() for o in overrides or [] if o and o.strip()]
    return (loader.apply_overrides(RAW, ov) if ov else RAW), ov


def _usage(raw, installed, priority):
    """Resource use of the installed set alone (the 'before' needles)."""
    if not installed:
        return []
    guests = loader.load_guest_data(raw)
    scn = {"installed": dict(installed)}
    for kw in ({"baseline": True, "allow_removal": False}, {"allow_removal": False}):
        plan, _ = solve_model(build_problem(raw, guests, scn, priority, **kw))
        if plan is not None:
            return _usage_table(evaluate(plan, guests, loader.load_ship_budget(raw)), loader.load_ship_budget(raw))
    return []


def _demand_usage(raw, scn, priority):
    """When the candidate cannot be admitted: what the ship WOULD carry with no capacity limit,
    so the over-budget needles show which classes break."""
    from governor.admission import _demand_plan
    guests = loader.load_guest_data(raw)
    plan = _demand_plan(raw, guests, scn, priority, minimal=False)
    if plan is None:
        return []
    budget = loader.load_ship_budget(raw)
    return _usage_table(evaluate(plan, guests, budget), budget)


# ---------------------------------------------------------------- meta
@app.get("/api/meta")
def meta():
    guests = loader.load_guest_data(RAW)
    out = {"guests": {}, "priorities": {}, "scenarios": {}, "budget": {}}
    for g, G in sorted(guests.items()):
        out["guests"][g] = {"name": G.name, "mass_kg": G.mass_kg, "safety_critical": G.safety_critical,
                            "configs": [{"id": c.id, "preferred": c.preferred, "issues": c.issues} for c in G.configs]}
    for p, d in sorted(RAW["priority"].items()):
        out["priorities"][p] = d["weights"]
    for name, path in SCN.items():
        out["scenarios"][name] = loader.load_scenario(path)
    b = loader.load_ship_budget(RAW)
    out["budget"] = {k: v for k, v in b.items() if not isinstance(v, (list, dict))}
    out["response_time"] = RAW["ship"]["response_time"]
    out["ship"] = RAW["ship"]          # knob defaults are read from here, never typed in the page
    out["card"] = RAW["card"]
    return jsonify(_json(out))


# ---------------------------------------------------------------- A / A′
@app.post("/api/admit")
def admit():
    q = request.get_json(force=True)
    try:
        raw, ov = _raw_with(q.get("overrides"))
    except Exception as e:                                  # bad override path → tell the user, not a 500
        return jsonify({"error": f"override: {e}"}), 400
    base = loader.load_scenario(SCN[q.get("scenario", "A_landlord")])
    scn = copy.deepcopy(base)
    if "installed" in q:
        scn["installed"] = q["installed"]
    scn["candidate"] = q.get("candidate") or scn.get("candidate")
    scn["state"] = {**scn.get("state", {}), **(q.get("state") or {})}
    if q.get("swap") is not None:
        if q["swap"]:
            scn["swap"] = q["swap"]
        else:
            scn.pop("swap", None)
    pr = q.get("priority") or scn.get("priority", "survey")
    if scn["candidate"] in scn["installed"] and not scn.get("swap"):
        return jsonify({"error": f"{scn['candidate']} is already installed — pick another candidate"}), 400

    r = classify_admission(raw, scn, pr, n_alternatives=int(q.get("alternatives", 4)))
    before = [u for u in _usage(raw, {g: c for g, c in scn["installed"].items() if g != scn["candidate"]}, pr)]
    after = r.get("usage") or []
    demand = []
    if not after and r.get("mode") != "at_sea":
        demand = _demand_usage(raw, scn, pr)
    r.pop("budget", None)
    r.pop("schema_errors", None)
    return jsonify(_json({"result": r, "before": before, "after": after, "demand": demand,
                          "overrides": ov, "priority": pr, "scenario": scn}))


# ---------------------------------------------------------------- A · decision board
ADMITTED = ("YES", "YES-IF")


def _why(r):
    """Reasons straight from the engine: the binding classes if something had to give,
    otherwise the three tightest resources of the admitted plan."""
    if r.get("binding_text"):
        return list(r["binding_text"])
    if r.get("verdict") in ("NO", "NOT-NOW"):
        return [r["sentence"]]
    rows = [u for u in r.get("usage") or [] if u.get("free_pct") is not None]
    return [f"{u['resource']}: {u['used']:g} of {u['capacity']:g} {u['unit']} ({u['free_pct']:g} % free)"
            for u in sorted(rows, key=lambda u: u["free_pct"])[:3]]


def _step(r):
    plan = r.get("plan") or {}
    inst = {g: plan["config"][g] for g, on in plan.get("installed", {}).items() if on} if plan else None
    return {"candidate": r["candidate"], "verdict": r["verdict"], "sentence": r["sentence"],
            "why": _why(r), "binding": r.get("binding", []),
            "actions": [a["text"] for a in r.get("actions", [])],
            "lowered": {g: m for g, m in plan.get("mode_n", {}).items() if m != "full"} if plan else {},
            "removed": plan.get("removed", []) if plan else [],
            "installed_after": inst, "value": r.get("value"),
            "U_after": plan["objective"]["U_normal"] if plan else None,
            "U_degraded": plan["objective"]["U_degraded"] if plan else None,
            "elapsed_s": r.get("elapsed_s")}


@app.post("/api/board")
def board():
    """Start from an installed set and judge every way to add the remaining G1–G5 cards:
    each one alone, and all of them one after another (both orders tried, the better one shown).
    Every verdict, reason and number is classify_admission's own."""
    q = request.get_json(force=True)
    try:
        raw, ov = _raw_with(q.get("overrides"))
    except Exception as e:
        return jsonify({"error": f"override: {e}"}), 400
    import itertools
    pr = q.get("priority", "survey")
    w = raw["priority"][pr]["weights"]
    installed = dict(q.get("installed") or {})
    state = {"location": "port", "crew": 14, **(q.get("state") or {})}
    # The default decision board intentionally covers official G1–G5 only.
    # A custom G6 is still available in the single admission selector.
    rest = [g for g in sorted(raw["card"]) if g in ("G1", "G2", "G3", "G4", "G5") and g not in installed]
    u_keep = sum(w.get(g, 1) for g in installed)
    before = _usage(raw, installed, pr)
    options = [{"id": "keep", "label": "Keep " + "+".join(installed), "adds": [], "verdict": "KEEP",
                "U": u_keep, "set": installed, "steps": [], "after": before, "demand": []}]
    details = {}
    for c in rest:
        scn = {"installed": installed, "candidate": c, "state": state}
        r = classify_admission(raw, scn, pr, n_alternatives=3)
        st = _step(r)
        after = r.get("usage") or []
        options.append({"id": "+" + c, "label": "+ " + c, "adds": [c], "verdict": r["verdict"],
                        "U": st["U_after"] if r["verdict"] in ADMITTED else None,
                        "set": st["installed_after"], "steps": [st], "after": after,
                        "demand": [] if after else _demand_usage(raw, scn, pr)})
        r.pop("budget", None)
        r.pop("schema_errors", None)
        details["+" + c] = r
    if len(rest) >= 2:
        best = None
        for order in itertools.permutations(rest):
            cur, steps, ok, last = dict(installed), [], True, None
            for c in order:
                r = classify_admission(raw, {"installed": cur, "candidate": c, "state": state}, pr, n_alternatives=0)
                steps.append(_step(r))
                last = r
                if r["verdict"] not in ADMITTED:
                    ok = False
                    break
                cur = steps[-1]["installed_after"]
            u = steps[-1]["U_after"] if ok else None
            cand = {"id": "+" + "+".join(order), "label": "+ " + " then ".join(order), "adds": list(order),
                    "verdict": (("YES-IF" if any(x["verdict"] == "YES-IF" for x in steps) else "YES") if ok
                                    else steps[-1]["verdict"]), "U": u, "set": cur if ok else None,
                    "steps": steps, "after": (last.get("usage") or []) if ok else [], "demand": [],
                    "all_aboard": ok and all(g in cur for g in order)}
            if best is None or (u or -1) > (best["U"] or -1):
                best = cand
        options.append(best)
    feasible = [o for o in options if o["U"] is not None]
    top = max(feasible, key=lambda o: (o["U"], -len(o["adds"])))
    for o in options:
        o["recommended"] = o is top
    return jsonify(_json({"priority": pr, "weights": w, "installed": installed, "before": before,
                          "options": options, "details": details, "overrides": ov}))


# ---------------------------------------------------------------- defaults (proposed combinations)
@lru_cache(maxsize=16)
def _defaults(priority: str, ov_key: str):
    raw, _ = _raw_with(json.loads(ov_key))
    t0 = time.perf_counter()
    rows = search_defaults(raw, [priority])
    return {"rows": rank(rows, priority), "infeasible": [r for r in rows if not r["feasible"]],
            "elapsed_s": round(time.perf_counter() - t0, 2)}


@app.post("/api/defaults")
def defaults():
    q = request.get_json(force=True)
    try:
        d = _defaults(q.get("priority", "survey"), json.dumps(sorted(q.get("overrides") or [])))
    except Exception as e:
        return jsonify({"error": f"override: {e}"}), 400
    return jsonify(_json(d))


# ---------------------------------------------------------------- B
@app.post("/api/b")
def scenario_b():
    q = request.get_json(force=True)
    sets = [o.strip() for o in q.get("overrides") or [] if o and o.strip()]
    raw_ov = [o for o in sets if not o.startswith("scn.")]
    scn_ov = [o[4:] for o in sets if o.startswith("scn.")]
    try:
        raw = loader.apply_overrides(RAW, raw_ov) if raw_ov else RAW
        scn = loader.load_scenario(SCN["B_right_of_way"])
        scn = loader.apply_overrides(scn, scn_ov) if scn_ov else scn
    except Exception as e:
        return jsonify({"error": f"override: {e}"}), 400
    crew = q.get("crew")
    d = right_of_way(raw, scn, q.get("priority", "survey"), crew=int(crew) if crew not in (None, "") else None)
    sim = d.pop("sim")
    for o in d["options"]:
        o.pop("sim", None)
    guests = loader.load_guest_data(raw)
    budget = loader.load_ship_budget(raw)
    aboard = scn["aboard"]
    static = {"mass_t": round(sum(guests[g].mass_kg for g in aboard) / 1000, 2),
              "mass_cap_t": budget["mass_kg"] / 1000,
              "cpu": sum((guests[g].compute or {}).get("cpu_cores", 0) or 0 for g in aboard),
              "cpu_cap": budget["cpu_cores"], "satcom_cap": budget["satcom_mbps"]}
    weights = raw["priority"][q.get("priority", "survey")]["weights"]
    return jsonify(_json({"decision": d, "rows": sim.rows, "log": sim.log, "caps": sim.caps, "lost": sim.lost,
                          "static": static, "aboard": aboard, "weights": weights, "overrides": sets}))


@app.get("/api/physical-g6")
def physical_g6():
    """Show one independent G6 monitoring snapshot; not real fire automation."""
    from physical_model.snapshot import load_snapshot
    runtime = ROOT / "scenarios" / "G6_monitoring.json"
    if not runtime.is_file():
        return jsonify({"status": "UNKNOWN", "assessment_status": "UNKNOWN",
                        "full_admission_status": "NOT_EVALUATED",
                        "note": "G6_monitoring.json not found in this checkout"})
    try:
        report = load_snapshot(runtime_path=runtime)
        return jsonify(_json({
            "status": report["status"],
            "assessment_status": report["assessment_status"],
            "full_admission_status": report["full_admission_status"],
            "resources": {name: block["status"] for name, block in report["resources"].items()},
            "violations": [v["constraint_id"] for v in report["constraint_violations"]],
            "unresolved": [v["constraint_id"] for v in report["unresolved_constraints"]],
            "note": "Conditional selected-state screen; G6 fire triggering and full-envelope admission not evaluated."
        }))
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return jsonify({"status": "UNKNOWN", "assessment_status": "UNKNOWN",
                        "full_admission_status": "NOT_EVALUATED",
                        "note": f"G6 physical snapshot unavailable: {type(exc).__name__}: {exc}"})


@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5050)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    app.run(host=a.host, port=a.port, debug=False)
