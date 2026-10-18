"""Entry point:  python -m d1_reference.cli [--candidate G3 G4] [--priority survey_primary] [--set guests.G4.power_kw=60]"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

from .admission import decide
from .explain import render_text, to_dict
from .model import load_bundle


def _default_root() -> Path:
    # repo root = two levels above src/governor
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "config" / "platform.yaml").exists():
            return parent
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="governor", description="Scenario A admission (D1) — resource governor")
    ap.add_argument("--root", type=Path, default=_default_root(), help="directory holding config/, cards/, scenarios/")
    ap.add_argument("--scenario", type=Path, default=None, help="scenario YAML (default: <root>/scenarios/a.yaml)")
    ap.add_argument("--candidate", nargs="+", default=None, help="candidate card id(s); default from the scenario file")
    ap.add_argument("--priority", nargs="+", default=None, help="priority file name(s); default: all")
    ap.add_argument("--set", dest="overrides", nargs="+", action="extend", default=[], metavar="PATH=VALUE",
                    help="jury override applied in memory only, e.g. guests.G4.power_kw=60")
    ap.add_argument("--format", choices=["text", "json", "both"], default="both")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    t0 = time.perf_counter()
    bundle = load_bundle(args.root, overrides=args.overrides, scenario_path=args.scenario)
    candidates = args.candidate or list(bundle.scenario.candidates)
    priorities = args.priority or list(bundle.priority_names())
    if not candidates:
        print("no candidate given and the scenario lists none", file=sys.stderr)
        return 2

    results = []
    for cand in candidates:
        for prio in priorities:
            d = decide(bundle, cand, prio)
            results.append(d)
            if args.format in ("text", "both"):
                print(render_text(bundle, d))
                print()
    if args.format in ("json", "both"):
        payload = [to_dict(bundle, d) for d in results]
        if args.format == "both":
            print("--- JSON ---")
        print(json.dumps(payload if len(payload) != 1 else payload[0], indent=2))
    if args.format in ("text", "both"):
        print(f"[{len(results)} decision(s) in {time.perf_counter() - t0:.2f} s]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
