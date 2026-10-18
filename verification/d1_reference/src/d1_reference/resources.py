"""Resource-class registry.

A resource class knows two things: how much the platform offers (capacity) and how much
a guest in a given mode takes (demand). The solver only iterates this list, so adding
cooling later is one new entry here plus its name in config/governor.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from .model import Guest, Mode, Platform

CapacityFn = Callable[[Platform], float]
DemandFn = Callable[[Guest, Mode, Platform], float]


@dataclass(frozen=True)
class Resource:
    name: str
    unit: str
    capacity: CapacityFn
    demand: DemandFn
    description: str = ""

    def demand_of(self, guest: Guest, mode: Mode, platform: Platform) -> float:
        if mode is Mode.REMOVE:
            return 0.0
        return self.demand(guest, mode, platform)


# ------------------------------------------------------------------ demand functions

def _power(guest: Guest, mode: Mode, _pf: Platform) -> float:
    if mode is Mode.LOW:
        if guest.low_power_kw is None:
            raise ValueError(f"{guest.id} has no low-power mode")
        return guest.low_power_kw
    return guest.power_kw


def _mass(guest: Guest, _mode: Mode, _pf: Platform) -> float:
    # mass does not change with power mode; the hardware stays aboard
    return guest.mass_t


def _stability(guest: Guest, _mode: Mode, pf: Platform) -> float:
    return sum(p.mass_t * pf.stability_multiplier[p.at] for p in guest.parts)


# ------------------------------------------------------------------ registry

REGISTRY: Dict[str, Resource] = {
    r.name: r for r in [
        Resource("power", "kW", lambda pf: pf.power_reserve_kw, _power,
                 "continuous electrical reserve available to guests (A.1 / A.9)"),
        Resource("mass", "t", lambda pf: pf.mass_margin_t, _mass,
                 "mass margin (A.4)"),
        Resource("stability", "t-eq", lambda pf: pf.stability_budget_t_eq, _stability,
                 "stability budget, mass x position multiplier (A.4)"),
        # Later: Resource("cooling", "kW", lambda pf: pf.cooling_capacity_kw(...), _heat, ...)
    ]
}


def active_resources(names: Optional[Sequence[str]] = None) -> List[Resource]:
    """Resources in the order given (default: registry order). Unknown names are an error."""
    chosen = list(names) if names is not None else list(REGISTRY)
    missing = [n for n in chosen if n not in REGISTRY]
    if missing:
        raise KeyError(f"unknown resource class(es) {missing}; registry has {sorted(REGISTRY)}")
    return [REGISTRY[n] for n in chosen]
