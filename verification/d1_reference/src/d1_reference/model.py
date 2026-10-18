"""Inputs: load YAML, apply overrides in memory, build typed dataclasses.

All numbers come from files under <root>/config, <root>/cards, <root>/scenarios.
Overrides ("guests.G4.power_kw=60") are applied to the merged in-memory dict only;
no file is ever written.
"""
from __future__ import annotations

import copy
import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml


class Mode(enum.Enum):
    """Operating mode chosen for a guest in an admission plan."""
    FULL = "FULL"
    LOW = "LOW"
    REMOVE = "REMOVE"


@dataclass(frozen=True)
class Part:
    name: str
    mass_t: float
    at: str  # position class: deck / hangar / mast (key of platform.stability_multiplier)


@dataclass(frozen=True)
class Guest:
    id: str
    name: str
    power_kw: float
    low_power_kw: Optional[float]
    parts: Tuple[Part, ...]
    capability: Mapping[str, str]  # mission -> high | medium | low

    @property
    def mass_t(self) -> float:
        return sum(p.mass_t for p in self.parts)

    @property
    def has_low_power(self) -> bool:
        return self.low_power_kw is not None


@dataclass(frozen=True)
class Platform:
    name: str
    power_reserve_kw: float
    mass_margin_t: float
    stability_budget_t_eq: float
    stability_multiplier: Mapping[str, float]
    extra: Mapping[str, Any] = field(default_factory=dict)  # anything else in platform.yaml (e.g. nominal reserve)


@dataclass(frozen=True)
class SolverParams:
    time_limit_s: float
    seed: int
    num_workers: int
    scale: int
    margin_resolution: int


@dataclass(frozen=True)
class Scenario:
    name: str
    installed: Tuple[str, ...]
    candidates: Tuple[str, ...]
    priorities: Tuple[str, ...]  # empty -> all priority files


@dataclass(frozen=True)
class Bundle:
    """Everything one admission decision needs, after overrides."""
    platform: Platform
    guests: Mapping[str, Guest]
    priorities: Mapping[str, Mapping[str, float]]  # priority name -> mission -> weight
    levels: Mapping[str, float]
    default_level: str
    low_power_retained: float
    resource_names: Tuple[str, ...]
    solver: SolverParams
    n_alternatives: int
    scenario: Scenario
    overrides: Tuple[str, ...]
    raw: Mapping[str, Any]  # merged dict after overrides, for traceability / JSON

    @property
    def installed(self) -> Tuple[str, ...]:
        return self.scenario.installed

    def priority_names(self) -> Tuple[str, ...]:
        return self.scenario.priorities or tuple(self.priorities)


# ----------------------------------------------------------------------------- loading

def _read_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_raw(root: Path, scenario_path: Optional[Path] = None) -> Dict[str, Any]:
    """Read every input file into one merged dict (no overrides yet)."""
    root = Path(root)
    scenario_path = Path(scenario_path) if scenario_path else root / "scenarios" / "a.yaml"
    raw: Dict[str, Any] = {
        "platform": _read_yaml(root / "config" / "platform.yaml"),
        "governor": _read_yaml(root / "config" / "governor.yaml"),
        "guests": {},
        "priorities": {},
        "scenario": _read_yaml(scenario_path),
    }
    for card in sorted((root / "cards").glob("*.yaml")):
        data = _read_yaml(card)
        gid = data.get("id", card.stem)
        raw["guests"][gid] = data
    for pfile in sorted((root / "config" / "priorities").glob("*.yaml")):
        data = _read_yaml(pfile)
        raw["priorities"][data.get("name", pfile.stem)] = data["weights"]
    return raw


def parse_override(text: str) -> Tuple[List[str], Any]:
    """'guests.G4.power_kw=60' -> (['guests','G4','power_kw'], 60). Value parsed as YAML."""
    if "=" not in text:
        raise ValueError(f"override must look like path.to.key=value, got {text!r}")
    key, val = text.split("=", 1)
    path = [p for p in key.strip().split(".") if p]
    if not path:
        raise ValueError(f"empty override path in {text!r}")
    return path, yaml.safe_load(val)


def apply_override(raw: Dict[str, Any], text: str) -> None:
    """Set one dotted path in the merged dict, in place. Lists are indexed by integer segments."""
    path, value = parse_override(text)
    node: Any = raw
    for seg in path[:-1]:
        if isinstance(node, list):
            node = node[int(seg)]
        elif isinstance(node, dict):
            if seg not in node:
                raise KeyError(f"override {text!r}: no key {seg!r} (have {sorted(node)})")
            node = node[seg]
        else:
            raise KeyError(f"override {text!r}: cannot descend into {seg!r}")
    last = path[-1]
    if isinstance(node, list):
        node[int(last)] = value
    elif isinstance(node, dict):
        node[last] = value  # may create a new key (e.g. give a guest a low_power_kw)
    else:
        raise KeyError(f"override {text!r}: cannot set {last!r}")


def build_bundle(raw: Mapping[str, Any], overrides: Sequence[str] = ()) -> Bundle:
    """Deep-copy the merged dict, apply scenario + CLI overrides, build dataclasses."""
    data = copy.deepcopy(dict(raw))
    scenario_overrides = list(data["scenario"].get("overrides") or [])
    all_overrides = scenario_overrides + list(overrides)
    for ov in all_overrides:
        apply_override(data, ov)

    pf = data["platform"]
    known = {"name", "power_reserve_kw", "mass_margin_t", "stability_budget_t_eq", "stability_multiplier"}
    platform = Platform(
        name=pf.get("name", "platform"),
        power_reserve_kw=float(pf["power_reserve_kw"]),
        mass_margin_t=float(pf["mass_margin_t"]),
        stability_budget_t_eq=float(pf["stability_budget_t_eq"]),
        stability_multiplier={k: float(v) for k, v in pf["stability_multiplier"].items()},
        extra={k: v for k, v in pf.items() if k not in known},
    )

    guests: Dict[str, Guest] = {}
    for gid, g in data["guests"].items():
        parts = tuple(Part(name=str(p.get("name", f"part{i}")), mass_t=float(p["mass_t"]), at=str(p["at"]))
                      for i, p in enumerate(g["parts"]))
        for p in parts:
            if p.at not in platform.stability_multiplier:
                raise ValueError(f"{gid}: part {p.name!r} at unknown position {p.at!r}; "
                                 f"platform knows {sorted(platform.stability_multiplier)}")
        lp = g.get("low_power_kw")
        guests[gid] = Guest(
            id=gid, name=str(g.get("name", gid)),
            power_kw=float(g["power_kw"]),
            low_power_kw=None if lp is None else float(lp),
            parts=parts,
            capability={str(m): str(l) for m, l in g["capability"].items()},
        )

    gov = data["governor"]
    sp = gov["solver"]
    solver = SolverParams(
        time_limit_s=float(sp["time_limit_s"]), seed=int(sp["seed"]), num_workers=int(sp["num_workers"]),
        scale=int(sp["scale"]), margin_resolution=int(sp["margin_resolution"]),
    )
    sc = data["scenario"]
    scenario = Scenario(
        name=str(sc.get("name", "scenario")),
        installed=tuple(sc["installed"]),
        candidates=tuple(sc.get("candidates") or []),
        priorities=tuple(sc.get("priorities") or []),
    )
    for gid in scenario.installed + scenario.candidates:
        if gid not in guests:
            raise KeyError(f"scenario names guest {gid!r} but no card cards/{gid}.yaml was loaded")

    levels = {str(k): float(v) for k, v in gov["levels"].items()}
    default_level = str(gov.get("default_capability_level", "low"))
    for g in guests.values():
        for mission, level in g.capability.items():
            if level not in levels:
                raise ValueError(f"{g.id}: capability {mission}={level!r} not in levels {sorted(levels)}")

    return Bundle(
        platform=platform, guests=guests,
        priorities={name: {str(m): float(w) for m, w in ws.items()} for name, ws in data["priorities"].items()},
        levels=levels, default_level=default_level,
        low_power_retained=float(gov["low_power_capability_retained"]),
        resource_names=tuple(gov["resources"]),
        solver=solver,
        n_alternatives=int(gov.get("report", {}).get("alternatives", 5)),
        scenario=scenario,
        overrides=tuple(all_overrides),
        raw=data,
    )


def load_bundle(root: Path, overrides: Sequence[str] = (), scenario_path: Optional[Path] = None) -> Bundle:
    """One-call loader: files -> merged dict -> overrides -> Bundle."""
    return build_bundle(load_raw(root, scenario_path), overrides)
