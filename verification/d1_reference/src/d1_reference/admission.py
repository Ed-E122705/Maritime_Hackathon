"""Scenario A admission (D1) as a lexicographic CP-SAT optimisation.

Decision per installed guest: FULL / LOW (if the card has a low-power mode) / REMOVE.
The candidate is forced FULL. Objective: maximise CI (mission-weighted capability kept),
then with CI fixed maximise MI (free share of the tightest resource).

Every capacity constraint carries an assumption literal. If the model is infeasible the
solver returns a sufficient set of those literals; a deletion filter shrinks it to a
minimal core so only resources that truly cause the refusal are reported.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from .model import Bundle, Guest, Mode
from .resources import Resource, active_resources

Plan = Dict[str, Mode]


# ----------------------------------------------------------------------------- plain-python evaluation

@dataclass(frozen=True)
class Usage:
    used: float
    capacity: float
    unit: str

    @property
    def free(self) -> float:
        return self.capacity - self.used

    @property
    def free_frac(self) -> float:
        return self.free / self.capacity

    @property
    def over(self) -> bool:
        return self.used > self.capacity + 1e-9

    @property
    def overshoot_frac(self) -> float:
        """how far over capacity, as a share of capacity (negative when under)."""
        return self.used / self.capacity - 1.0


@dataclass(frozen=True)
class Evaluation:
    plan: Mapping[str, Mode]
    usage: Mapping[str, Usage]
    ci: float            # capability index, %
    mi: float            # margin index, % free of the tightest resource
    tightest: str
    violated: Tuple[str, ...]

    @property
    def feasible(self) -> bool:
        return not self.violated


@dataclass(frozen=True)
class Option:
    mode: Mode
    retained: float  # share of the guest's capability kept in this mode


def options_for(bundle: Bundle, gid: str, force_full: bool = False) -> List[Option]:
    opts = [Option(Mode.FULL, 1.0)]
    if force_full:
        return opts
    if bundle.guests[gid].has_low_power:
        opts.append(Option(Mode.LOW, bundle.low_power_retained))
    opts.append(Option(Mode.REMOVE, 0.0))
    return opts


def retained_fraction(bundle: Bundle, mode: Mode) -> float:
    return {Mode.FULL: 1.0, Mode.LOW: bundle.low_power_retained, Mode.REMOVE: 0.0}[mode]


def capability_value(bundle: Bundle, gid: str, priority: str) -> float:
    """Mission-weighted capability of a guest at FULL under one priority file."""
    guest = bundle.guests[gid]
    weights = bundle.priorities[priority]
    return sum(w * bundle.levels[guest.capability.get(mission, bundle.default_level)]
               for mission, w in weights.items())


def evaluate(bundle: Bundle, plan: Plan, priority: str, resources: Sequence[Resource],
             reference_plan: Optional[Plan] = None) -> Evaluation:
    """Usage, CI and MI of a plan. CI denominator = everyone in `reference_plan` (default: plan) at FULL."""
    pf = bundle.platform
    usage: Dict[str, Usage] = {}
    for r in resources:
        cap = r.capacity(pf)
        if cap <= 0:
            raise ValueError(f"resource {r.name}: capacity must be positive, got {cap}")
        used = sum(r.demand_of(bundle.guests[g], mode, pf) for g, mode in plan.items())
        usage[r.name] = Usage(used=used, capacity=cap, unit=r.unit)
    denominator_guests = list(reference_plan or plan)
    full = sum(capability_value(bundle, g, priority) for g in denominator_guests)
    kept = sum(capability_value(bundle, g, priority) * retained_fraction(bundle, mode) for g, mode in plan.items())
    ci = 100.0 * kept / full if full else 100.0
    tightest = min(usage, key=lambda n: usage[n].free_frac)
    mi = 100.0 * usage[tightest].free_frac
    violated = tuple(n for n, u in usage.items() if u.over)
    return Evaluation(plan=dict(plan), usage=usage, ci=ci, mi=mi, tightest=tightest, violated=violated)


def enumerate_plans(bundle: Bundle, candidate: str, priority: str, resources: Sequence[Resource]) -> List[Evaluation]:
    """Brute force over installed guests' modes; feasible plans ranked by CI then MI. Also the cross-check."""
    installed = list(bundle.installed)
    mode_lists = [[o.mode for o in options_for(bundle, g)] for g in installed]
    rows: List[Evaluation] = []
    for combo in itertools.product(*mode_lists):
        plan: Plan = dict(zip(installed, combo))
        plan[candidate] = Mode.FULL
        ev = evaluate(bundle, plan, priority, resources)
        if ev.feasible:
            rows.append(ev)
    rows.sort(key=lambda e: (-round(e.ci, 6), -round(e.mi, 6), _plan_key(e.plan)))
    return rows


def _plan_key(plan: Mapping[str, Mode]) -> Tuple[str, ...]:
    return tuple(f"{g}:{m.value}" for g, m in sorted(plan.items()))


# ----------------------------------------------------------------------------- CP-SAT model

@dataclass
class _Built:
    model: cp_model.CpModel
    choice: Dict[str, List[Tuple[Option, Any]]]      # gid -> [(option, boolvar)]
    value: Any                                       # LinearExpr: scaled capability kept
    mi: Any                                          # IntVar: margin index in 1/margin_resolution
    limits: Dict[str, Any]                           # resource -> assumption literal
    use: Dict[str, Any]                              # resource -> LinearExpr (scaled)


def _scaled(x: float, scale: int) -> int:
    return int(round(x * scale))


def build_model(bundle: Bundle, candidate: str, priority: str, resources: Sequence[Resource],
                force_full: bool = False) -> _Built:
    S, R = bundle.solver.scale, bundle.solver.margin_resolution
    pf = bundle.platform
    m = cp_model.CpModel()
    aboard = list(bundle.installed) + [candidate]

    use_terms: Dict[str, list] = {r.name: [] for r in resources}
    value_terms: list = []
    choice: Dict[str, List[Tuple[Option, Any]]] = {}
    for gid in aboard:
        guest = bundle.guests[gid]
        opts = options_for(bundle, gid, force_full=force_full or gid == candidate)
        bools = [m.NewBoolVar(f"{gid}_{o.mode.value}") for o in opts]
        m.AddExactlyOne(bools)
        choice[gid] = list(zip(opts, bools))
        v = capability_value(bundle, gid, priority)
        for o, b in choice[gid]:
            for r in resources:
                d = _scaled(r.demand_of(guest, o.mode, pf), S)
                if d:
                    use_terms[r.name].append(d * b)
            kept = _scaled(v * o.retained, S)
            if kept:
                value_terms.append(kept * b)

    use = {name: cp_model.LinearExpr.Sum(terms) if terms else 0 for name, terms in use_terms.items()}
    value = cp_model.LinearExpr.Sum(value_terms) if value_terms else 0

    # one assumption literal per capacity constraint -> infeasibility cores name resources
    limits: Dict[str, Any] = {}
    margins = []
    lo = -R * 1000  # allows up to 1000x overshoot before the margin variable saturates
    for r in resources:
        cap = _scaled(r.capacity(pf), S)
        lit = m.NewBoolVar(f"limit_{r.name}")
        m.Add(use[r.name] <= cap).OnlyEnforceIf(lit)
        limits[r.name] = lit
        # margin_r (in 1/R) <= free share:  margin_r * cap <= (cap - use_r) * R
        mr = m.NewIntVar(lo, R, f"margin_{r.name}")
        m.Add(mr * cap <= (cap - use[r.name]) * R)
        margins.append(mr)
    m.AddAssumptions(list(limits.values()))
    mi = m.NewIntVar(lo, R, "MI")
    m.AddMinEquality(mi, margins)
    return _Built(model=m, choice=choice, value=value, mi=mi, limits=limits, use=use)


def make_solver(bundle: Bundle) -> cp_model.CpSolver:
    s = cp_model.CpSolver()
    s.parameters.num_workers = bundle.solver.num_workers
    s.parameters.random_seed = bundle.solver.seed
    s.parameters.max_time_in_seconds = bundle.solver.time_limit_s
    return s


def _core_names(built: _Built, solver: cp_model.CpSolver) -> List[str]:
    idx = set(solver.SufficientAssumptionsForInfeasibility())
    return [name for name, lit in built.limits.items() if lit.Index() in idx]


def minimal_core(bundle: Bundle, built: _Built, core: Sequence[str], reference: Evaluation,
                 stats: "SolveStats") -> List[str]:
    """Deletion filter. Try to drop each resource from the core; keep the drop if the rest is still infeasible.

    Deletion is attempted in ascending order of overshoot at the reference plan, so when several
    resources would each alone refuse the candidate, the one furthest over its budget survives.
    """
    # start from the solver's core plus everything plain arithmetic sees over budget, so the
    # result depends on this ordering rule and not on which core the solver happened to return
    start = set(core) | set(reference.violated)
    order = sorted(start, key=lambda n: (reference.usage[n].overshoot_frac, n))
    keep = list(order)
    for name in order:
        trial = [k for k in keep if k != name]
        if not trial:
            continue
        built.model.ClearAssumptions()
        built.model.AddAssumptions([built.limits[k] for k in trial])
        status = make_solver(bundle).Solve(built.model)
        stats.record(status)
        if status == cp_model.INFEASIBLE:
            keep = trial
    built.model.ClearAssumptions()
    built.model.AddAssumptions(list(built.limits.values()))
    return [n for n in built.limits if n in keep]  # back to reporting order


# ----------------------------------------------------------------------------- decision

@dataclass
class SolveStats:
    solves: int = 0
    statuses: List[str] = field(default_factory=list)
    wall_s: float = 0.0

    def record(self, status: int) -> None:
        self.solves += 1
        self.statuses.append(_status_name(status))


def _status_name(status: int) -> str:
    return {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE", cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "MODEL_INVALID", cp_model.UNKNOWN: "UNKNOWN"}.get(status, str(status))


@dataclass(frozen=True)
class Change:
    guest: str
    name: str
    frm: Mode
    to: Mode
    power_before_kw: float
    power_after_kw: float
    capability: Mapping[str, str]       # what the guest offers (mission -> level)
    value_lost: float                   # mission-weighted capability lost
    ci_points_lost: float               # percentage points of CI lost


@dataclass
class Decision:
    scenario: str
    candidate: str
    candidate_name: str
    priority: str
    installed: Tuple[str, ...]
    verdict: str                         # YES | YES-IF | NO
    binding: Tuple[str, ...]             # minimal core (resources that truly bind)
    violated: Tuple[str, ...]            # every resource over budget at the reference plan
    baseline: Evaluation                 # everyone (installed + candidate) at FULL
    alone: Evaluation                    # candidate alone at FULL
    plan: Optional[Evaluation]           # recommended plan (None for NO)
    changes: Tuple[Change, ...]
    alternatives: Tuple[Evaluation, ...] # feasible plans ranked by CI then MI
    overrides: Tuple[str, ...]
    stats: SolveStats
    judged_against: Mapping[str, Any]

    @property
    def tightest(self) -> Optional[str]:
        return self.plan.tightest if self.plan else None


def decide(bundle: Bundle, candidate: str, priority: str) -> Decision:
    t0 = time.perf_counter()
    stats = SolveStats()
    resources = active_resources(bundle.resource_names)
    if candidate not in bundle.guests:
        raise KeyError(f"unknown candidate {candidate!r}; cards: {sorted(bundle.guests)}")
    if candidate in bundle.installed:
        raise ValueError(f"candidate {candidate} is already installed")
    if priority not in bundle.priorities:
        raise KeyError(f"unknown priority {priority!r}; have {sorted(bundle.priorities)}")

    aboard = list(bundle.installed) + [candidate]
    full_plan: Plan = {g: Mode.FULL for g in aboard}
    baseline = evaluate(bundle, full_plan, priority, resources)
    alone = evaluate(bundle, {candidate: Mode.FULL}, priority, resources, reference_plan=full_plan)

    common = dict(scenario=bundle.scenario.name, candidate=candidate, candidate_name=bundle.guests[candidate].name,
                  priority=priority, installed=tuple(bundle.installed), baseline=baseline, alone=alone,
                  overrides=tuple(bundle.overrides), stats=stats,
                  judged_against={r.name: {"capacity": r.capacity(bundle.platform), "unit": r.unit} for r in resources})

    # Stage 1: maximise capability kept
    built = build_model(bundle, candidate, priority, resources)
    built.model.Maximize(built.value)
    solver = make_solver(bundle)
    status = solver.Solve(built.model)
    stats.record(status)
    if status == cp_model.INFEASIBLE:
        core = minimal_core(bundle, built, _core_names(built, solver), alone, stats)
        stats.wall_s = time.perf_counter() - t0
        return Decision(verdict="NO", binding=tuple(core), violated=alone.violated, plan=None, changes=(),
                        alternatives=(), **common)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"CP-SAT stage 1 ended with {_status_name(status)}")
    best_value = int(round(solver.ObjectiveValue()))

    # Stage 2: keep that capability, maximise the tightest margin
    built.model.Add(built.value >= best_value)
    built.model.Maximize(built.mi)
    status2 = solver.Solve(built.model)
    stats.record(status2)
    if status2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"CP-SAT stage 2 ended with {_status_name(status2)}")
    plan: Plan = {gid: next(o.mode for o, b in opts if solver.Value(b)) for gid, opts in built.choice.items()}
    chosen = evaluate(bundle, plan, priority, resources)
    alternatives = enumerate_plans(bundle, candidate, priority, resources)

    if baseline.feasible:
        verdict, binding = "YES", ()
    else:
        verdict = "YES-IF"
        b_built = build_model(bundle, candidate, priority, resources, force_full=True)
        b_solver = make_solver(bundle)
        b_status = b_solver.Solve(b_built.model)
        stats.record(b_status)
        if b_status == cp_model.INFEASIBLE:
            binding = tuple(minimal_core(bundle, b_built, _core_names(b_built, b_solver), baseline, stats))
        else:  # rounding edge: python says over, solver says fits -> report what python saw
            binding = baseline.violated

    changes = tuple(_change(bundle, gid, plan[gid], priority, baseline) for gid in bundle.installed
                    if plan[gid] is not Mode.FULL)
    stats.wall_s = time.perf_counter() - t0
    return Decision(verdict=verdict, binding=binding, violated=baseline.violated, plan=chosen, changes=changes,
                    alternatives=tuple(alternatives), **common)


def _change(bundle: Bundle, gid: str, mode: Mode, priority: str, baseline: Evaluation) -> Change:
    g = bundle.guests[gid]
    v = capability_value(bundle, gid, priority)
    lost = v * (1.0 - retained_fraction(bundle, mode))
    full_total = sum(capability_value(bundle, x, priority) for x in baseline.plan)
    return Change(guest=gid, name=g.name, frm=Mode.FULL, to=mode,
                  power_before_kw=g.power_kw,
                  power_after_kw=0.0 if mode is Mode.REMOVE else float(g.low_power_kw),
                  capability=dict(g.capability), value_lost=lost,
                  ci_points_lost=100.0 * lost / full_total if full_total else 0.0)
