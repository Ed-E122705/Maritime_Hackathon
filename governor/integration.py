"""Bridge: canonical physical inputs -> existing decision optimizer, plus independent snapshot.

All physical source data come from physical_model/data and data/guests. The
optimizer-only YAML supplies unverified policy/envelope choices, not alternate
ship engineering facts. Snapshots are conditional and do not certify D1 or D3.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sync_ship_config(ship: dict, specs: dict) -> tuple[dict, list[str]]:
    s = copy.deepcopy(ship)
    notes = []
    elec = specs["electrical"]
    for band, gensets in elec["reserve_kw_by_speed"].items():
        for key, n in (("reserve_kw", "2"), ("degraded_reserve_kw", "1")):
            old = s["power"][key].get(band)
            value = gensets[n]
            if old != value:
                notes.append(f"ship.power.{key}.{band}: {old} -> {value} kW (physical ship_specs authority)")
            s["power"][key][band] = value
    s["power"]["peak_extra_kw"] = elec["peak_extra_kw"]["2"]
    s["power"]["peak_extra_degraded_kw"] = elec["peak_extra_kw"]["1"]
    s["power"]["peak_max_seconds"] = elec["peak_max_duration_s"]
    lines = elec["lines_kw"]
    if len(set(lines.values())) != 1:
        raise ValueError("Decision solver assumes equal mission-line capacities; cannot translate unequal lines")
    s["power"]["line_capacity_kw"] = next(iter(lines.values()))
    s["power"]["lines"] = list(lines)
    cool = specs["cooling"]
    s["cooling"].update(capacity_at_12c_kw=cool["cold_kw"], capacity_at_30c_kw=cool["hot_kw"],
                        degraded_factor=1-cool["fault_loss_fraction"])
    pos = specs["positions"]
    for src, dst in (("bay1", "bay1"), ("bay2", "bay2")):
        P = pos[src]
        s["positions"][dst].update(max_mass_t=P["mass_limit_kg"]/1000,
                                     length_m=P["dimensions_m"][0], width_m=P["dimensions_m"][1],
                                     height_m=P["dimensions_m"][2],
                                     fraction_capacity=P["units"]/2 if src=="bay1" else P["units"])
    mast = [v for v in pos.values() if v.get("kind")=="mast"]
    if not mast or len(set(v["mass_limit_kg"] for v in mast)) != 1:
        raise ValueError("Mast capacities require manual mapping")
    s["positions"]["mast_slot"].update(total=len(mast), occupied=sum(v["reserved"] for v in mast),
                     max_mass_kg=mast[0]["mass_limit_kg"], max_area_m2=mast[0]["area_limit_m2"])
    roof=pos["roof"]
    s["positions"]["hangar_roof"]["capacity"]=roof["units"]
    s["positions"]["flight_deck_hangar"]["capacity"]=pos["hangar"]["units"]
    s["mass"]["margin_t"] = specs["mass"]["margin_kg"]/1000
    s["mass"]["stability_budget_t_eq"] = specs["mass"]["stability_budget_kg_eq"]/1000
    s["mass"]["stability_multiplier"].update({
        "bay1": pos["bay1"]["stability_multiplier"],
        "bay2": pos["bay2"]["stability_multiplier"],
        "flight_deck_hangar": pos["hangar"]["stability_multiplier"],
        "hangar_roof": pos["roof"]["stability_multiplier"],
        "mast_slot": mast[0]["stability_multiplier"],
    })
    s["cooling"]["mast_air_cooled_max_kw"] = mast[0]["air_heat_limit_kw"]
    s["data"].update(backbone_mbps=specs["datalinks"]["backbone"]["max_mbps"],
                     satcom_mbps=specs["datalinks"]["satcom"]["max_mbps"],
                     los_radio_mbps=specs["datalinks"]["los"]["max_mbps"],
                     acoustic_kbps=specs["datalinks"]["acoustic"]["max_mbps"]*1000)
    comp=specs["compute"]
    nodes=comp["nodes"]
    if len(set((v["cores"],v["ram_gb"],v["accelerators"]) for v in nodes.values())) != 1:
        raise ValueError("Heterogeneous compute nodes need a revised optimizer; do not silently aggregate")
    s["compute"].update(nodes=len(nodes), cores_per_node=next(iter(nodes.values()))["cores"],
         ram_gb_per_node=next(iter(nodes.values()))["ram_gb"],
         accelerators_per_node=next(iter(nodes.values()))["accelerators"],
         storage_tb=comp["shared_storage_tb"],allocatable_fraction=comp["guest_fraction"])
    # Node-4 has no guest accelerators; pooled D1 feasibility may be overoptimistic.
    if any(v.get("guest_accelerators") != v.get("accelerators") for v in nodes.values()):
        notes.append("Compute optimizer pools accelerators; physical per-node check is mandatory (node4 guest accelerator restricted)")
    for physical_key, legacy_key, factor in (("admission","admission_s",1/1000),
        ("arbitration","arbitration_s",1/1000),("first_shed","first_shed_s",1/1000),
        ("full_shed","full_shed_s",1/1000),("safety_command","safety_command_ms",1)):
        s["response_time"][legacy_key] = specs["timing_ms"][physical_key] * factor
    unsupported=set(s["envelope"]["speed_bands"])-set(elec["reserve_kw_by_speed"])
    if unsupported:
        raise ValueError(f"Mission envelope includes speed bands not defined in physical ship_specs: {sorted(unsupported)}")
    notes.append("D1 uses pooled compute and 2-GW/sustained-windows approximation; physical model checks selected state only")
    notes.append("Optimizer-only values (crane time, wiring, transient sequence, crew policy) remain explicit YAML assumptions")
    return s,notes


def sync_guest_profiles(overlay: dict, profiles: dict) -> tuple[dict,list[str]]:
    result=copy.deepcopy(overlay)
    notes=[]
    for gid, p in profiles["guest_resource_profiles"].items():
        if gid not in result:
            # Fail on an undeclared governor role, rather than silently inventing its semantics.
            continue
        active = p.get("compute_by_mode", {})
        if active:
            # Conservatively reserve max per resource across declared physical modes.
            mx={k:max(float(v.get(k,0)) for v in active.values()) for k in ("cores","ram_gb","accelerators","storage_tb")}
            actual={"cpu_cores":mx["cores"],"ram_gb":mx["ram_gb"],
                    "accelerator_units":mx["accelerators"],"storage_gb":mx["storage_tb"]*1000}
            if result[gid].get("compute") != actual:
                notes.append(f"{gid} compute profile aligned to physical resource_profiles (conservative max over modes)")
            result[gid]["compute"] = actual
        if gid == "G3" and p.get("survey_power_kw") is not None and result[gid].get("full"):
            old = result[gid]["full"].get("kw")
            result[gid]["full"]["kw"] = p["survey_power_kw"]
            if old != p["survey_power_kw"]:
                notes.append(f"G3 ship-side survey demo load {old} -> {p['survey_power_kw']} kW")
    return result,notes


def plan_to_physical_state(plan: dict, raw: dict, context: dict|None=None) -> tuple[dict,list[str]]:
    """Translate admitted guest choice; do not invent unsupported off/standby load.

    Uses explicit demo base state only for parameters not supplied by optimizer.
    Those are returned as evidence gaps, not verified observations.
    """
    from physical_model.ship_state import ShipState
    context = context or {}
    state = ShipState.from_files().to_dict()
    issues = ["Unobserved environmental/link/timing state uses packaged simulation fixture.",
              "This evaluates one selected state, NOT concurrent windows or the mission envelope."]
    state.update(gensets_online=2, seawater_c=30, cooling_fault=False,
                 speed_band="cruise", speed_kn=10, ship_location="in_port")
    for key in ("seawater_c","sea_state","wind_kn","crew"):
        if key in context:
            state[key]=context[key]
    if context.get("location") in ("at_sea","port"):
        state["ship_location"]="at_sea" if context["location"]=="at_sea" else "in_port"
    for gid, card in raw["card"].items():
        on=bool(plan.get("installed",{}).get(gid))
        if not on:
            state["guests"][gid]={"installed":False}
            continue
        role=plan.get("mode_n",{}).get(gid)
        role_cfg=raw["overlay"].get(gid,{}).get(role)
        if not role_cfg or "power_mode" not in role_cfg:
            if gid=="G3" and role=="full":
                power_mode="standby";operation="surveying"
            else:
                issues.append(f"{gid} role {role}: no canonical power mode (synthetic/off); cannot assert physical snapshot for this plan")
                return {}, issues
        else:
            power_mode=role_cfg["power_mode"]
            operation=None
            if gid=="G1" and power_mode=="active": operation="passive_sensing"
            if gid=="G5": operation="operating"
            if gid=="G6": operation=power_mode
        config=plan.get("config",{}).get(gid)
        if config not in {x["id"] for x in card["placement"]["configurations"]}:
            issues.append(f"{gid}: missing/invalid configuration {config}")
            return {}, issues
        # A solver assignment can change power-line wiring in memory (Jury override).
        # Here we honor exactly the plan's point->line map, rather than a static sample.
        cfg=next(x for x in card["placement"]["configurations"] if x["id"]==config)
        point=None
        for a in cfg["assignments"]:
            loc=a["location"]
            if loc in ("bay1","bay2","flight_deck_hangar","mast_slot"):
                point={"flight_deck_hangar":"flight_deck","mast_slot":"mast"}.get(loc,loc)
                break
        power_line=plan.get("lines",{}).get(point) if point is not None else None
        if power_line is None:
            issues.append(f"{gid}: no power-line choice exposed for physical validator")
            return {},issues
        state["guests"][gid] = {"installed":True,"placement":config,"power_mode":power_mode,
                                "operation":operation,"power_line":power_line}
    return state,issues


def crosscheck_admission(result: dict,raw:dict,scenario:dict)->dict:
    """Independent evidence-aware screen of D1 plan; never upgrades a D1 YES to certified."""
    plan=result.get("plan")
    if not plan:
        return {"status":"NOT_EVALUATED","reason":"No selected installation plan (refusal or underway decision)"}
    try:
        from physical_model.snapshot import build_snapshot
        from physical_model.manifest_adapter import load_json, ROOT as PMROOT
        from physical_model.ship_state import ShipState
        state,issues=plan_to_physical_state(plan,raw,scenario.get("state",{}))
        if not state:
            return {"status":"UNKNOWN","reason":"Untranslatable solver role/placement", "gaps":issues}
        pm=PMROOT / "physical_model/data"
        spec=load_json(pm/"ship_specs.json")
        profile=load_json(pm/"resource_profiles.json")
        report=build_snapshot(spec,ShipState.from_dict(state),
                              list(raw["card"].values()),profile)
        # Jury overrides may edit optimizer ship capacities without touching
        # physical ship_specs. Such a hypothetical is not certified by this
        # base physical snapshot, even if the underlying model returns PASS.
        from . import loader
        baseline_ship,_ = sync_ship_config(
            __import__("yaml").safe_load((PMROOT/"config/ship.yaml").read_text(encoding="utf-8")), spec)
        mismatch = []
        for area, keys in (("power",("reserve_kw","degraded_reserve_kw","line_capacity_kw")),
                           ("cooling",("capacity_at_12c_kw","capacity_at_30c_kw","degraded_factor")),
                           ("data",("backbone_mbps","satcom_mbps","los_radio_mbps")),
                           ("mass",("margin_t","stability_budget_t_eq"))):
            for key in keys:
                if baseline_ship[area][key]!=raw["ship"][area][key]:
                    mismatch.append(f"Optimizer ship override {area}.{key} differs from physical ship_specs")
        checks={"status":report["status"],"timing_status":report["timing_status"],
                "assessment_status":report["assessment_status"],"full_admission_status":report["full_admission_status"],
                "failed_constraints":[v["constraint_id"] for v in report["constraint_violations"]],
                "unresolved_constraints":[v["constraint_id"] for v in report["unresolved_constraints"]],
                "gaps":issues+report["host_evidence_gaps"],"basis":"One conditional physical snapshot; not a mission-envelope or transition certificate"}
        if mismatch:
            checks["status"]="UNKNOWN"
            checks["gaps"].extend(mismatch)
            checks["reason"]="Hypothetical ship override is not represented by the authoritative physical model"
        return checks
    except Exception as exc:
        return {"status":"UNKNOWN","reason":f"Physical-model bridge could not evaluate: {type(exc).__name__}: {exc}"}
