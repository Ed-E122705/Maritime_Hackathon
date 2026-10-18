"""Command line.

  python -m governor.cli admit   --scenario scenarios/A_landlord.yaml [--candidate G4] [--priority rescue]
                                 [--set card.G4.resources.power_modes.charging_initial.power_kw.nominal=20]
  python -m governor.cli defaults [--priority survey]      # default-combination search
  python -m governor.cli matrix   --scenario scenarios/A_landlord.yaml   # every card × every priority
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import loader
from .admission import classify_admission
from .defaults import rank, search_defaults

RESULTS = loader.ROOT / "results"


def _scenario(args):
    scn = loader.load_scenario(Path(args.scenario)) if args.scenario else {}
    if args.candidate:
        scn["candidate"] = args.candidate
    if getattr(args, "state", None):
        for kv in args.state:
            k, v = kv.split("=", 1)
            scn.setdefault("state", {})[k] = loader.yaml.safe_load(v)
    return scn


def print_admission(r: dict, out=sys.stdout):
    p = lambda *a: print(*a, file=out)
    p(f"\n=== D1 admission · candidate {r['candidate']} · priority file '{r['priority']}' ===")
    p(f"VERDICT: {r['verdict']}   ({r.get('elapsed_s', '?')} s; ceiling 30 s)")
    p(r["sentence"])
    if r.get("warning"):
        p(f"WARNING: {r['warning']}")
    if r.get("binding_text"):
        p("Binding constraint(s):")
        for t in r["binding_text"]:
            p(f"  - {t}")
    if r.get("actions"):
        p("Ranked displacement / throttle list (least capability lost first):")
        for i, a in enumerate(r["actions"], 1):
            p(f"  {i}. {a['text']}")
    if r.get("placement"):
        p("Placement (D2):")
        for g, t in r["placement"].items():
            p(f"  {g}: {t}")
    if r.get("placement_options"):
        p(f"Placement options for {r['candidate']} (D2, alternatives considered):")
        for o in r["placement_options"]:
            tag = "preferred" if o["preferred"] else "tolerated"
            p(f"  - {o['config']} ({tag}): {o['status']}" + (f" — {o['reason']}" if o.get("reason") else ""))
    if r.get("usage"):
        p("Budget against the mission envelope:")
        for u in r["usage"]:
            p(f"  {u['resource']:<30} {u['used']:>9} / {u['capacity']:<9} {u['unit']:<7} free {u['free_pct']}%")
    if r.get("stress"):
        p("Stress states (not in the default envelope, reported for honesty):")
        for s in r["stress"]:
            p(f"  - {s['sentence']}")
    if r.get("operability"):
        p("Envelope operability (ship-state conditions):")
        for n in r["operability"]:
            p(f"  - {n}")
    if r.get("standing_rules"):
        p("Standing operating rules created by this configuration:")
        for n in r["standing_rules"]:
            p(f"  - {n}")
    if r.get("alternatives"):
        p("Alternatives considered (next-best distinct plans):")
        for i, a in enumerate(r["alternatives"], 1):
            p(f"  {i}. {'; '.join(a['actions'])}  | U={a['U_normal']} U_deg={a['U_degraded']} margin={a['MI_pct']}%")
    if r.get("next_port_sentence"):
        p(f"At the next port call: {r['next_port_sentence']}")
    if r.get("solver_crosscheck"):
        p(f"!! independent evaluator disagrees with solver: {r['solver_crosscheck']}")
    if r.get("schema_errors"):
        p(f"Schema warnings: {r['schema_errors']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="governor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("admit")
    a.add_argument("--scenario", default=str(loader.ROOT / "scenarios/A_landlord.yaml"))
    a.add_argument("--candidate")
    a.add_argument("--priority")
    a.add_argument("--set", nargs="*", default=[], help="jury override(s), in memory only")
    a.add_argument("--state", nargs="*", default=[], help="ship state, e.g. location=at_sea crew=6")
    a.add_argument("--alternatives", type=int, default=4)
    a.add_argument("--json", action="store_true")
    d = sub.add_parser("defaults")
    d.add_argument("--priority", nargs="*")
    d.add_argument("--top", type=int, default=5)
    bb = sub.add_parser("b", help="Scenario B: right of way (D3) + degradation (D4)")
    bb.add_argument("--scenario", default=str(loader.ROOT / "scenarios/B_right_of_way.yaml"))
    bb.add_argument("--priority", default="survey")
    bb.add_argument("--crew", type=int)
    bb.add_argument("--set", nargs="*", default=[],
                    help="overrides: card.*/ship.*/priority.* as for admit, or scn.* on the scenario, "
                         "e.g. scn.timeline.1.reserve_kw=60")
    bb.add_argument("--json", action="store_true")
    mx = sub.add_parser("matrix")
    mx.add_argument("--scenario", default=str(loader.ROOT / "scenarios/A_landlord.yaml"))
    args = ap.parse_args(argv)

    raw = loader.load_raw()
    if args.cmd == "admit":
        scn = _scenario(args)
        overrides = list(scn.get("overrides", [])) + args.set
        raw = loader.apply_overrides(raw, overrides)
        pr = args.priority or scn.get("priority", "survey")
        if overrides:
            print(f"Jury overrides (in memory): {', '.join(overrides)}")
        r = classify_admission(raw, scn, pr, n_alternatives=args.alternatives)
        if args.json:
            print(json.dumps(r, indent=1, default=str))
        else:
            print_admission(r)
        return 0
    if args.cmd == "b":
        from .rightofway import right_of_way, print_b
        scn = loader.load_scenario(Path(args.scenario))
        raw_ov = [o for o in args.set if not o.startswith("scn.")]
        scn_ov = [o[4:] for o in args.set if o.startswith("scn.")]
        raw = loader.apply_overrides(raw, raw_ov)
        scn = loader.apply_overrides(scn, scn_ov)
        if args.set:
            print(f"Jury overrides (in memory): {', '.join(args.set)}")
        d = right_of_way(raw, scn, args.priority, crew=args.crew)
        if args.json:
            d = {k: v for k, v in d.items() if k != "sim"} | {"log": d["sim"].log, "rows": d["sim"].rows}
            for o in d["options"]:
                o.pop("sim", None)
            print(json.dumps(d, indent=1, default=str))
        else:
            print_b(d)
        return 0
    if args.cmd == "defaults":
        rows = search_defaults(raw, args.priority)
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / "defaults.json").write_text(json.dumps(rows, indent=1, default=str))
        for pr in (args.priority or sorted(raw["priority"])):
            print(f"\n=== default sets · priority '{pr}' (top {args.top}) ===")
            for r in rank(rows, pr)[:args.top]:
                print(f"  {'+'.join(r['set']):<10} U={r['U_normal']:>5}/{r['U_max']:<5} U_deg={r['U_degraded']:<5} "
                      f"margin={r['MI_pct']}%  jury verdicts={r.get('verdict_mix')}  mean U after card={r.get('U_after_mean')}")
            bad = [r for r in rows if r["priority"] == pr and not r["feasible"]]
            if bad:
                print(f"  infeasible as a default: {', '.join('+'.join(r['set']) + ' (' + ', '.join(r['binding']) + ')' for r in bad)}")
        return 0
    if args.cmd == "matrix":
        scn = loader.load_scenario(Path(args.scenario))
        out = []
        for pr in sorted(raw["priority"]):
            for c in sorted(raw["card"]):
                if c in scn["installed"]:
                    continue
                r = classify_admission(raw, {**scn, "candidate": c}, pr, n_alternatives=0)
                out.append((pr, c, r["verdict"], r["sentence"], r.get("elapsed_s")))
                print(f"{pr:<16} {c}  {r['verdict']:<8} {r.get('elapsed_s')}s  {r['sentence']}")
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / "matrix.json").write_text(json.dumps(out, indent=1))
        return 0


if __name__ == "__main__":
    sys.exit(main())
