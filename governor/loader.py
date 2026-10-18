"""Inputs: guest cards (JSON, schema-validated), guest overlays, ship budget, mission envelope,
priority files, scenario files and jury overrides.

Function names follow Whole_model.docx §8: validate_manifest, load_guest_data, load_ship_budget,
load_mission_envelope. Nothing here decides anything; it only turns files into numbers.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
LOCATION_TO_POINT = {"bay1": "bay1", "bay2": "bay2", "flight_deck_hangar": "flight_deck",
                     "hangar_roof": "flight_deck", "mast_slot": "mast"}
POWERED_LOCATIONS = {"bay1", "bay2", "flight_deck_hangar", "mast_slot"}


# ----------------------------------------------------------------------------- raw config
def load_raw(root: Path = ROOT) -> dict:
    """Load authoritative VesselOS manifests/specs. No independent guest copy is used.

    The YAML contains optimization-only policy, installation windows, and demo
    scenarios; overlapping host limits are synchronized from ship_specs.json.
    Pure decision-team checkout is supported for its legacy tests but emits a
    warning in this case. Deploy with physical_model/ and data/guests/ present.
    """
    root = Path(root)
    cards_dir = root / "data" / "guests"
    schema_file = root / "data" / "guest_schema.json"
    using_physical = (root / "physical_model" / "data" / "ship_specs.json").exists()
    if not cards_dir.is_dir():
        cards_dir = root / "guests"     # standalone compatibility only
        schema_file = cards_dir / "guest_schema.json"
    ship = yaml.safe_load((root / "config" / "ship.yaml").read_text(encoding="utf-8"))
    overlay = yaml.safe_load((root / "config" / "guest_overlays.yaml").read_text(encoding="utf-8"))
    raw = {"ship": ship, "overlay": overlay,
           "schema": json.loads(schema_file.read_text(encoding="utf-8")),
           "card": {}, "priority": {}, "source_notes": []}
    if using_physical:
        from .integration import sync_ship_config, sync_guest_profiles
        specs = json.loads((root / "physical_model/data/ship_specs.json").read_text(encoding="utf-8"))
        profiles = json.loads((root / "physical_model/data/resource_profiles.json").read_text(encoding="utf-8"))
        raw["ship"], notes = sync_ship_config(ship, specs)
        raw["source_notes"].extend(notes)
        raw["overlay"], notes = sync_guest_profiles(overlay, profiles)
        raw["source_notes"].extend(notes)
    for p in sorted(cards_dir.glob("G*.json")):
        txt = p.read_text(encoding="utf-8").strip()
        if not txt:
            raise ValueError(f"Empty canonical guest file: {p}; no silent skip")
        card = json.loads(txt)
        gid = card["id"]
        if gid in raw["card"]:
            raise ValueError(f"Duplicate guest id {gid} in {cards_dir}")
        if gid != p.name.split("_")[0].split(".")[0]:
            raise ValueError(f"Guest ID {gid} does not match filename {p.name}")
        if gid not in raw["overlay"]:
            raise ValueError(f"Missing decision role profile for {gid}; add to config/guest_overlays.yaml")
        raw["card"][gid] = card
    if not raw["card"]:
        raise ValueError(f"No canonical guests in {cards_dir}")
    for p in sorted((root / "config/priorities").glob("*.yaml")):
        raw["priority"][p.stem] = yaml.safe_load(p.read_text(encoding="utf-8"))
    return raw


def apply_overrides(raw: dict, overrides: list[str]) -> dict:
    """Jury overrides in memory only (files on disk never change).

    Path forms:  ship.power.reserve_kw.cruise=180
                 card.G4.resources.power_modes.charging_initial.power_kw.nominal=20
                 overlay.G3.full.kw=3
                 priority.survey.weights.G2=8
    A list of objects is indexed by the objects' "id" (or by a number).
    """
    raw = copy.deepcopy(raw)
    for ov in overrides:
        key, val = ov.split("=", 1)
        parts = key.split(".")
        node = raw
        for p in parts[:-1]:
            node = _step(node, p)
        last = parts[-1]
        value = yaml.safe_load(val)
        if isinstance(node, list):
            idx = _list_index(node, last)
            node[idx] = value
        else:
            if last not in node:
                raise KeyError(f"override path not found: {key}")
            node[last] = value
    return raw


def _list_index(lst, p):
    if p.isdigit():
        return int(p)
    for i, item in enumerate(lst):
        if isinstance(item, dict) and item.get("id") == p:
            return i
    raise KeyError(f"no list item with id={p}")


def _step(node, p):
    if isinstance(node, list):
        return node[_list_index(node, p)]
    if p not in node:
        raise KeyError(f"override path not found at '{p}'")
    return node[p]


# ----------------------------------------------------------------------------- validation
def validate_manifest(card: dict, schema: dict) -> list[str]:
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in v.iter_errors(card)]


# ----------------------------------------------------------------------------- guests
@dataclass
class PlacementConfig:
    id: str
    preferred: bool
    assignments: list           # [{component, location, fraction, area_m2, mass_kg}]
    point: str                  # power connection point
    stability_kg_eq: float
    mass_by_location: dict
    issues: list = field(default_factory=list)   # reasons this config can never be used


@dataclass
class Guest:
    id: str
    name: str
    safety_critical: bool
    mass_kg: float
    components: dict            # id -> mass_kg
    configs: list
    modes: dict                 # role -> {kw, capability}
    windows: list               # [{id, total_kw, delta_kw, minutes, interruptible, defer_capability}]
    chilled: bool
    needs_bay_clear: bool
    compute: dict
    data: dict
    data_nominal: dict
    install_port_minutes: float
    install_entries: list
    port_only_components: set
    op_modes: list
    capability_levels: dict
    conflicts: list             # [(my_mode, other_guest, other_mode, reason)]
    excludes: list
    requires: list
    card: dict


def _power_mode(card, mid):
    for pm in card["resources"]["power_modes"]:
        if pm["id"] == mid:
            return pm
    raise KeyError(f"{card['id']}: power mode {mid} not in card")


def _mode_from_overlay(card, spec):
    if spec is None:
        return None
    if "power_mode" in spec:
        pm = _power_mode(card, spec["power_mode"])
        kw = pm["power_kw"]["nominal"]
        cap = spec.get("capability", pm.get("capability_fraction"))
        if cap is None:
            cap = 1.0
        return {"kw": float(kw), "capability": float(cap), "source": f"card:{spec['power_mode']}"}
    return {"kw": float(spec["kw"]), "capability": float(spec["capability"]), "source": "overlay"}


def load_guest_data(raw: dict) -> dict[str, Guest]:
    ship = raw["ship"]
    pos = ship["positions"]
    mult = ship["mass"]["stability_multiplier"]
    guests = {}
    for gid, card in raw["card"].items():
        ov = raw["overlay"][gid]
        comps = {c["id"]: float(c["mass_kg"] or 0) for c in card["assembly"]["components"]}
        modes = {}
        for role in ("full", "low", "standby", "off"):
            m = _mode_from_overlay(card, ov.get(role))
            if m is not None:
                modes[role] = m
        if card["criticality"]["safety_critical"]:
            modes.pop("off", None)
            modes.pop("standby", None)
        windows = []
        for w in ov.get("windows", []):
            pm = _power_mode(card, w["power_mode"])
            total = float(pm["power_kw"]["nominal"])
            windows.append({"id": f"{gid}.{w['id']}", "guest": gid, "total_kw": total,
                            "delta_kw": max(0.0, total - modes["full"]["kw"]),
                            "minutes": pm["max_duration_minutes"],
                            "interruptible": bool(w["interruptible"]),
                            "defer_capability": float(w["defer_capability"])})
        configs = []
        for pc in card["placement"]["configurations"]:
            asg, stab, mass_loc, issues = [], 0.0, {}, []
            point = None
            for a in pc["assignments"]:
                loc = a["location"]
                m = comps[a["component_id"]]
                frac = a["bay_fraction"]
                asg.append({"component": a["component_id"], "location": loc,
                            "fraction": frac if frac is not None else 0.0,
                            "area_m2": a["area_m2"], "mass_kg": m})
                stab += m * mult[loc]
                mass_loc[loc] = mass_loc.get(loc, 0.0) + m
                if point is None and loc in POWERED_LOCATIONS:
                    point = LOCATION_TO_POINT[loc]
                # static per-position limits (A.3)
                if loc == "mast_slot":
                    if m > pos["mast_slot"]["max_mass_kg"]:
                        issues.append(f"{a['component_id']} {m:.0f} kg > mast limit {pos['mast_slot']['max_mass_kg']} kg")
                    if a["area_m2"] is not None and a["area_m2"] > pos["mast_slot"]["max_area_m2"]:
                        issues.append(f"{a['component_id']} {a['area_m2']} m² > mast slot {pos['mast_slot']['max_area_m2']} m²")
                if loc == "flight_deck_hangar" and "drone" in a["component_id"].lower():
                    if m > pos["flight_deck_hangar"]["max_vtol_kg"]:
                        issues.append(f"VTOL {m:.0f} kg > hangar limit {pos['flight_deck_hangar']['max_vtol_kg']} kg")
                if m / 1000 > ship["installation"]["crane_max_lift_t"]:
                    issues.append(f"{a['component_id']} exceeds crane lift {ship['installation']['crane_max_lift_t']} t")
            for loc, m in mass_loc.items():
                if loc in ("bay1", "bay2") and m / 1000 > pos[loc]["max_mass_t"]:
                    issues.append(f"{m/1000:.2f} t > {loc} limit {pos[loc]['max_mass_t']} t")
            # air cooling at the mast (A.2): the powered component sits at the mast
            if point == "mast" and ov.get("cooling") == "air":
                if modes["full"]["kw"] > ship["cooling"]["mast_air_cooled_max_kw"]:
                    issues.append(f"{modes['full']['kw']} kW > mast air-cooling limit {ship['cooling']['mast_air_cooled_max_kw']} kW")
            if point == "mast" and ov.get("cooling") != "air":
                issues.append("mast has no chilled-water manifold (A.2)")
            if any(a["location"] == "hangar_roof" for a in asg) and not pos["hangar_roof"]["drone_clearance_verified"]:
                issues.append("hangar-roof antenna: drone clearance not verified")
            configs.append(PlacementConfig(pc["id"], pc["preferred"], asg, point or "none", stab, mass_loc, issues))
        install_port = sum(float(e["duration_minutes"] or 0) for e in card["installation"]
                           if e["port_only"] and e["component_ids"])
        port_only = {c for e in card["installation"] if e["port_only"] for c in e["component_ids"]}
        conflicts = [(om["id"], c["guest_id"], c["guest_mode"], c["reason"])
                     for om in card["operational_modes"] for c in om.get("conflicts", [])]
        guests[gid] = Guest(
            id=gid, name=card["name"], safety_critical=card["criticality"]["safety_critical"],
            mass_kg=sum(comps.values()), components=comps, configs=configs, modes=modes,
            windows=windows, chilled=(ov.get("cooling") != "air"),
            needs_bay_clear=bool(ov.get("needs_bay_clear")), compute=ov["compute"], data=ov["data"],
            data_nominal=ov.get("data_nominal", {}), install_port_minutes=install_port,
            install_entries=card["installation"], port_only_components=port_only,
            op_modes=card["operational_modes"], capability_levels=card["capability"]["value_by_mission"],
            conflicts=conflicts, excludes=card["assembly"]["excludes"],
            requires=card["assembly"]["requires"], card=card)
    return guests


# ----------------------------------------------------------------------------- ship & envelope
def cooling_capacity_kw(ship: dict, seawater_c: float) -> float:
    c = ship["cooling"]
    t = min(max(seawater_c, 12.0), 30.0)
    return c["capacity_at_12c_kw"] + (c["capacity_at_30c_kw"] - c["capacity_at_12c_kw"]) * (t - 12.0) / 18.0


def load_mission_envelope(raw: dict) -> dict:
    return raw["ship"]["envelope"]


def load_ship_budget(raw: dict, env: dict | None = None) -> dict:
    """Capacities the verdict is judged against: worst case over the mission envelope (A.10)."""
    ship = raw["ship"]
    env = env or load_mission_envelope(raw)
    bands = env["speed_bands"]
    band_n = min(bands, key=lambda b: ship["power"]["reserve_kw"][b])
    band_d = min(bands, key=lambda b: ship["power"]["degraded_reserve_kw"][b])
    t_max = max(env["seawater_c"])
    cool = cooling_capacity_kw(ship, t_max)
    comp = ship["compute"]
    frac = comp["allocatable_fraction"]
    budget = {
        "power_kw": ship["power"]["reserve_kw"][band_n], "power_band": band_n,
        "line_kw": ship["power"]["line_capacity_kw"], "lines": ship["power"]["lines"],
        "wiring": ship["power"]["wiring"],
        "cooling_kw": cool, "seawater_c": t_max,
        "mass_kg": ship["mass"]["margin_t"] * 1000,
        "stability_kg_eq": ship["mass"]["stability_budget_t_eq"] * 1000,
        "satcom_mbps": ship["data"]["satcom_mbps"], "backbone_mbps": ship["data"]["backbone_mbps"],
        "los_radio_mbps": ship["data"]["los_radio_mbps"],
        "cpu_cores": comp["nodes"] * comp["cores_per_node"] * frac,
        "ram_gb": comp["nodes"] * comp["ram_gb_per_node"] * frac,
        "accelerator_units": int(comp["nodes"] * comp["accelerators_per_node"] * frac),  # indivisible → floor
        "storage_gb": comp["storage_tb"] * 1000 * frac,
        "mast_free": ship["positions"]["mast_slot"]["total"] - ship["positions"]["mast_slot"]["occupied"],
        "roof_requires_hangar_guest": bool(ship["positions"]["hangar_roof"]["requires_hangar_guest"]),
        "bay1_fraction": ship["positions"]["bay1"]["fraction_capacity"],
        "bay2_fraction": ship["positions"]["bay2"]["fraction_capacity"],
        "hangar_capacity": ship["positions"]["flight_deck_hangar"]["capacity"],
        "roof_capacity": ship["positions"]["hangar_roof"]["capacity"],
        "bay1_max_kg": ship["positions"]["bay1"]["max_mass_t"] * 1000,
        "bay2_max_kg": ship["positions"]["bay2"]["max_mass_t"] * 1000,
        "port_window_min": ship["installation"]["port_window_hours"] * 60,
        "removal_factor": ship["installation"]["removal_time_factor"],
        "degraded": [],
        "stress": [],
    }
    if env.get("genset_down_possible"):
        budget["degraded"].append({"name": "genset_down", "power_kw": ship["power"]["degraded_reserve_kw"][band_d],
                                   "cooling_kw": cool, "lost_line": ship["power"]["degraded_lost_line"],
                                   "label": f"one genset down ({band_d} band, {ship['power']['degraded_reserve_kw'][band_d]} kW)"})
    cool_fail = {"name": "cooling_failure", "power_kw": budget["power_kw"],
                 "cooling_kw": cool * ship["cooling"]["degraded_factor"], "lost_line": "none",
                 "label": f"cooling loop −40 % at {t_max:g} °C ({cool*ship['cooling']['degraded_factor']:.0f} kW)"}
    both = {"name": "genset_and_cooling", "power_kw": ship["power"]["degraded_reserve_kw"][band_d],
            "cooling_kw": cool * ship["cooling"]["degraded_factor"], "lost_line": ship["power"]["degraded_lost_line"],
            "label": "genset down AND cooling loop −40 %"}
    if env.get("cooling_loop_failure_possible"):
        budget["degraded"].append(cool_fail)
    else:
        budget["stress"].append(cool_fail)
    budget["stress"].append(both)
    return budget


def load_scenario(path: Path) -> dict:
    return yaml.safe_load(open(path))
