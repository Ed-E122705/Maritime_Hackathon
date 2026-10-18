"""Rationale text and JSON, generated from the numbers of the decision — never canned strings."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping

from .admission import Change, Decision, Evaluation
from .model import Bundle, Mode


def _num(x: float) -> str:
    """Compact number: 10 -> '10', 12.07 -> '12.07', 0.045 -> '0.045'."""
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return s if s else "0"


def shortfall(ev: Evaluation, resource: str) -> str:
    u = ev.usage[resource]
    return f"{resource} needs {_num(u.used)} {u.unit} vs {_num(u.capacity)} {u.unit} available"


def headroom(ev: Evaluation, resource: str) -> str:
    u = ev.usage[resource]
    return f"{resource} {u.free_frac * 100:.1f} % free ({_num(u.used)} of {_num(u.capacity)} {u.unit} used)"


def describe_plan(bundle: Bundle, ev: Evaluation) -> str:
    bits = []
    for gid in bundle.installed:
        mode = ev.plan[gid]
        g = bundle.guests[gid]
        if mode is Mode.REMOVE:
            bits.append(f"remove {gid}")
        elif mode is Mode.LOW:
            bits.append(f"{gid} low-power ({_num(g.power_kw)}→{_num(g.low_power_kw)} kW)")
    return ", ".join(bits) or "no change"


def change_sentence(ch: Change) -> str:
    caps = ", ".join(f"{m} {lvl}" for m, lvl in ch.capability.items())
    if ch.to is Mode.REMOVE:
        return (f"remove {ch.guest} ({ch.name}): loses all of its capability [{caps}], "
                f"−{ch.ci_points_lost:.1f} CI points")
    return (f"throttle {ch.guest} ({ch.name}) to low-power {_num(ch.power_before_kw)}→{_num(ch.power_after_kw)} kW: "
            f"keeps a reduced share of [{caps}], −{ch.ci_points_lost:.1f} CI points")


def headline(d: Decision) -> str:
    """One sentence a captain would accept, naming the binding constraint with live numbers."""
    if d.verdict == "YES":
        assert d.plan is not None
        return (f"YES — {d.candidate} fits with every installed guest at full; "
                f"tightest resource is {headroom(d.plan, d.plan.tightest)}.")
    if d.verdict == "YES-IF":
        assert d.plan is not None
        core = "; ".join(shortfall(d.baseline, r) for r in d.binding)
        extra = [r for r in d.violated if r not in d.binding]
        also = (" (" + "; ".join(shortfall(d.baseline, r) + " as well" for r in extra) + ")") if extra else ""
        return (f"YES-IF — with everyone at full, {core}{also}; "
                f"recommended: {describe_plan_short(d)} keeping {d.plan.ci:.1f} % of mission capability.")
    core = "; ".join(shortfall(d.alone, r) for r in d.binding)
    extra = [r for r in d.violated if r not in d.binding]
    also = (" (" + "; ".join(shortfall(d.alone, r) + " as well" for r in extra) + ")") if extra else ""
    return f"NO — even with every installed guest removed, {d.candidate} alone: {core}{also}."


def describe_plan_short(d: Decision) -> str:
    bits = []
    for ch in d.changes:
        if ch.to is Mode.REMOVE:
            bits.append(f"remove {ch.guest}")
        else:
            bits.append(f"{ch.guest} to low-power ({_num(ch.power_before_kw)}→{_num(ch.power_after_kw)} kW)")
    return ", ".join(bits) or "no change"


def usage_table(ev: Evaluation) -> List[str]:
    rows = []
    for name, u in ev.usage.items():
        flag = "  OVER" if u.over else ""
        rows.append(f"    {name:<10} {u.used:8.2f} / {_num(u.capacity):>6} {u.unit:<5} free {u.free_frac * 100:6.1f} %{flag}")
    return rows


def render_text(bundle: Bundle, d: Decision) -> str:
    out: List[str] = []
    out.append(f"=== Scenario {d.scenario} · candidate {d.candidate} ({d.candidate_name}) · priority = {d.priority} ===")
    out.append(f"Installed: {', '.join(d.installed)} · judged against one genset down "
               f"({_num(d.judged_against['power']['capacity'])} kW reserve)" if "power" in d.judged_against
               else f"Installed: {', '.join(d.installed)}")
    if d.overrides:
        out.append(f"Overrides: {', '.join(d.overrides)}")
    out.append(f"VERDICT: {headline(d)}")
    if d.binding:
        out.append(f"Binding constraint(s): {', '.join(d.binding)}")
        extra = [r for r in d.violated if r not in d.binding]
        if extra:
            out.append(f"Also over budget: {', '.join(extra)}")

    if d.verdict == "NO":
        out.append(f"  {d.candidate} alone at full:")
        out.extend(usage_table(d.alone))
        out.append(f"  Everyone at full would be:")
        out.extend(usage_table(d.baseline))
    else:
        assert d.plan is not None
        if d.changes:
            out.append("Recommended plan:")
            for ch in d.changes:
                out.append(f"  - {change_sentence(ch)}")
        out.append(f"  CI (capability kept) = {d.plan.ci:.1f} %   MI (tightest margin) = {d.plan.mi:.1f} % [{d.plan.tightest}]")
        out.extend(usage_table(d.plan))
        if d.alternatives:
            out.append(f"  Alternatives considered (feasible, ranked by CI then MI; {len(d.alternatives)} total):")
            for i, alt in enumerate(d.alternatives[: bundle.n_alternatives], 1):
                out.append(f"    {i}. {describe_plan(bundle, alt):<40} CI {alt.ci:5.1f} %  MI {alt.mi:5.1f} % [{alt.tightest}]")
    out.append(f"  solver: {d.stats.solves} CP-SAT solve(s), {d.stats.wall_s * 1000:.0f} ms total")
    return "\n".join(out)


# ----------------------------------------------------------------------------- JSON

def _eval_dict(ev: Evaluation) -> Dict[str, Any]:
    return {
        "plan": {g: m.value for g, m in ev.plan.items()},
        "ci_pct": round(ev.ci, 3),
        "mi_pct": round(ev.mi, 3),
        "tightest": ev.tightest,
        "feasible": ev.feasible,
        "violated": list(ev.violated),
        "usage": {
            name: {"used": round(u.used, 6), "capacity": u.capacity, "unit": u.unit,
                   "free_pct": round(u.free_frac * 100, 3), "over": u.over}
            for name, u in ev.usage.items()
        },
    }


def to_dict(bundle: Bundle, d: Decision) -> Dict[str, Any]:
    return {
        "scenario": d.scenario,
        "decision_class": "D1 admission",
        "candidate": d.candidate,
        "candidate_name": d.candidate_name,
        "priority": d.priority,
        "installed": list(d.installed),
        "overrides": list(d.overrides),
        "verdict": d.verdict,
        "headline": headline(d),
        "binding": list(d.binding),
        "violated": list(d.violated),
        "binding_detail": [shortfall(d.baseline if d.verdict != "NO" else d.alone, r) for r in d.binding],
        "judged_against": d.judged_against,
        "recommended": None if d.plan is None else {
            **_eval_dict(d.plan),
            "summary": describe_plan_short(d),
            "changes": [
                {"guest": c.guest, "name": c.name, "from": c.frm.value, "to": c.to.value,
                 "power_before_kw": c.power_before_kw, "power_after_kw": c.power_after_kw,
                 "capability": dict(c.capability), "value_lost": round(c.value_lost, 6),
                 "ci_points_lost": round(c.ci_points_lost, 3), "text": change_sentence(c)}
                for c in d.changes
            ],
        },
        "baseline_all_full": _eval_dict(d.baseline),
        "candidate_alone": _eval_dict(d.alone),
        "alternatives": [{**_eval_dict(a), "summary": describe_plan(bundle, a)}
                         for a in d.alternatives[: bundle.n_alternatives]],
        "n_feasible_plans": len(d.alternatives),
        "solver": {"solves": d.stats.solves, "statuses": list(d.stats.statuses), "wall_ms": round(d.stats.wall_s * 1000, 1),
                   "num_workers": bundle.solver.num_workers, "seed": bundle.solver.seed},
    }


def to_json(bundle: Bundle, d: Decision, **kw: Any) -> str:
    return json.dumps(to_dict(bundle, d), indent=kw.pop("indent", 2), sort_keys=False, **kw)
