"""Regenerate results/RESULTS.md: default-set ranking per priority file + Scenario A / A′ outcomes."""
from __future__ import annotations

import io
import json

from . import loader
from .admission import classify_admission
from .cli import print_admission
from .defaults import rank, search_defaults

CASES = [
    ("Default set (Annex B example) · jury card G3 · survey", "A_landlord", {"candidate": "G3"}, "survey", []),
    ("Same · priority swapped to rescue", "A_landlord", {"candidate": "G3"}, "rescue", []),
    ("Default set · jury card G4 · survey", "A_landlord", {"candidate": "G4"}, "survey", []),
    ("Jury changes one number: G4 initial charge 35 → 70 kW", "A_landlord", {"candidate": "G4"}, "survey",
     ["card.G4.resources.power_modes.charging_initial.power_kw.nominal=70"]),
    ("Jury changes one number: cooling at 30 °C 120 → 90 kW · rescue", "A_landlord", {"candidate": "G4"}, "rescue",
     ["ship.cooling.capacity_at_30c_kw=90"]),
    ("Impossible card: G4 continuous draw 130 kW", "A_landlord", {"candidate": "G4"}, "survey",
     ["card.G4.resources.power_modes.charging_followup.power_kw.nominal=130"]),
    ("Survey-max default (G1+G2+G3) · jury card G4 · survey", "A_landlord_survey_max", {"candidate": "G4"}, "survey", []),
    ("Survey-max default · jury card G4 · rescue", "A_landlord_survey_max", {"candidate": "G4"}, "rescue", []),
    ("Survey-max default · jury card G5 · survey (net loss)", "A_landlord_survey_max", {"candidate": "G5"}, "survey", []),
    ("Rescue-max default (G2+G4+G5) · jury card G3 · rescue", "A_landlord_rescue_max", {"candidate": "G3"}, "rescue", []),
    ("A′ under way · G4 card · crew 6", "A_landlord", {"candidate": "G4", "state": {"location": "at_sea", "crew": 6}}, "survey", []),
    ("A′ under way · G4 card · crew 0", "A_landlord", {"candidate": "G4", "state": {"location": "at_sea", "crew": 0}}, "survey", []),
    ("A′ drone swap at sea · crew 14 · window closed", "A_prime_drone_swap", {"state": {"crew": 14}}, "rescue", []),
    ("A′ drone swap at sea · crew 6 · window closed", "A_prime_drone_swap", {}, "rescue", []),
    ("A′ drone swap at sea · crew 6 · window open", "A_prime_drone_swap",
     {"state": {"crew": 6, "speed_kn": 6, "course": "steady", "deck": "clear"}}, "rescue", []),
]


def main():
    raw0 = loader.load_raw()
    rows = search_defaults(raw0)
    (loader.ROOT / "results").mkdir(exist_ok=True)
    (loader.ROOT / "results/defaults.json").write_text(json.dumps(rows, indent=1, default=str))
    md = ["# Results", "", "Regenerate with `make results` (deterministic: same inputs → same file).", "",
          "## 1. Default combinations (which three guests are aboard before the jury card)", "",
          "Ranking: every guest at full power first, then normal-envelope utility, degraded utility, "
          "mean utility after each possible jury card, tightest margin. Utility = Σ mission weight × capability.", ""]
    for pr in sorted(raw0["priority"]):
        md += [f"### Priority file: `{pr}`", "",
               "| Rank | Set | Utility | Degraded utility | Tightest margin | Jury cards → verdicts | Mean utility after card |",
               "|---|---|---|---|---|---|---|"]
        for i, r in enumerate(rank(rows, pr)[:6], 1):
            jv = ", ".join(f"{c}:{j['verdict']}" for c, j in r["jury"].items())
            md.append(f"| {i} | {'+'.join(r['set'])} | {r['U_normal']:g}/{r['U_max']:g} | {r['U_degraded']:g} | "
                      f"{r['MI_pct']}% | {jv} | {r['U_after_mean']:g} |")
        bad = [r for r in rows if r["priority"] == pr and not r["feasible"]]
        md += ["", "Infeasible as a starting set: " + ", ".join(f"{'+'.join(r['set'])} ({', '.join(r['binding'])})" for r in bad), ""]
    md += ["### Annex B example sets", ""]
    for pr in ("survey", "rescue"):
        for s in (["G1", "G2", "G5"], ["G2", "G3", "G4"]):
            r = next(x for x in rows if x["priority"] == pr and x["set"] == s)
            if r["feasible"]:
                md.append(f"* `{pr}` · {'+'.join(s)}: utility {r['U_normal']:g}/{r['U_max']:g}, margin {r['MI_pct']}%, "
                          f"jury cards → {', '.join(f'{c}:{j['verdict']}' for c, j in r['jury'].items())}")
            else:
                md.append(f"* `{pr}` · {'+'.join(s)}: **cannot be a starting set** — binding {', '.join(r['binding'])}")
    md += ["", "## 2. Scenario A / A′ decisions", ""]
    for title, scn_name, extra, pr, ovr in CASES:
        scn = loader.load_scenario(loader.ROOT / f"scenarios/{scn_name}.yaml")
        scn = {**scn, **{k: v for k, v in extra.items() if k != "state"}}
        if "state" in extra:
            scn["state"] = {**scn.get("state", {}), **extra["state"]}
        raw = loader.apply_overrides(raw0, ovr)
        r = classify_admission(raw, scn, pr, n_alternatives=3)
        buf = io.StringIO()
        print_admission(r, buf)
        md += [f"### {title}", ""]
        if ovr:
            md.append(f"Override: `{' '.join(ovr)}`  ")
        md += ["```", buf.getvalue().strip(), "```", ""]
    md += ["## 3. Scenario B — right of way (D3) and degradation (D4)", ""]
    from .rightofway import print_b, right_of_way
    scn0 = loader.load_scenario(loader.ROOT / "scenarios/B_right_of_way.yaml")
    for title, pr, crew, sov, rov in [
            ("Survey primary · crew 14", "survey", 14, [], []),
            ("Search-and-rescue primary · crew 14", "rescue", 14, [], []),
            ("Rescue primary · crew 6 (confirmation would miss the deadline → automatic)", "rescue", 6, [], []),
            ("Rescue primary · crew 0", "rescue", 0, [], []),
            ("Survey primary · jury sets the post-trip reserve to 60 kW", "survey", 14, ["timeline.1.reserve_kw=60"], []),
            ("Rescue primary · crew 6 with the deck occupied (no option meets the deadline)", "rescue", 6, ["initial.deck=occupied"], [])]:
        scn = loader.apply_overrides(scn0, sov)
        d = right_of_way(loader.apply_overrides(raw0, rov), scn, pr, crew=crew)
        buf = io.StringIO()
        print_b(d, buf)
        md += [f"### {title}", ""] + ([f"Override: `{' '.join(sov)}`  "] if sov else []) + ["```", buf.getvalue().strip(), "```", ""]
    (loader.ROOT / "results/RESULTS.md").write_text("\n".join(md) + "\n")
    print("wrote results/RESULTS.md and results/defaults.json")


if __name__ == "__main__":
    main()
