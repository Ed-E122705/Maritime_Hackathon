
import json
import hashlib
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]

register_path = ROOT / "physical_model/data/assumptions.json"
guest_path = ROOT / "data/guests/G6_automated_fire_detection_and_suppression.json"
profiles_path = ROOT / "physical_model/data/resource_profiles.json"

with open(register_path, encoding="utf-8") as file:
    register = json.load(file)

with open(guest_path, encoding="utf-8") as file:
    g6 = json.load(file)

with open(profiles_path, encoding="utf-8") as file:
    profiles = json.load(file)

g6_relative = "data/guests/G6_automated_fire_detection_and_suppression.json"
profiles_relative = "physical_model/data/resource_profiles.json"

# Register G6's actual source-file hash.
source_hash = hashlib.sha256(guest_path.read_bytes()).hexdigest()

source_record = {
    "file": g6_relative,
    "sha256": source_hash,
    "role": "User-defined G6 guest with explicitly disclosed synthetic demonstration values"
}

register["source_files"] = [
    item for item in register["source_files"]
    if item["file"] != g6_relative
]

register["source_files"].append(source_record)

# Record the simulation assumptions and their exact sources.
assumption = {
    "id": "G6-DEMO-01",
    "topic": "G6 simulated physical and resource requirements",
    "classification": "SYNTHETIC_DEMO_INPUT",

    "current_value": {
        "mass_kg": 500,
        "location": "bay2",
        "monitoring_power_kw": 2,
        "suppression_power_kw": 8,
        "cooling_type": "chilled_water",
        "backbone_mbps": 1,
        "compute_profile": profiles["guest_resource_profiles"]["G6"]
    },

    "why": (
        "The user-defined G6 concept does not provide these "
        "hardware specifications. Numerical values are chosen "
        "solely to exercise the resource governor."
    ),

    "source_refs": [
        {
            "file": g6_relative,
            "pointer": "/assembly/components/0/mass_kg",
            "value": g6["assembly"]["components"][0]["mass_kg"]
        },
        {
            "file": g6_relative,
            "pointer": "/resources/power_modes",
            "value": g6["resources"]["power_modes"]
        },
        {
            "file": g6_relative,
            "pointer": "/placement",
            "value": g6["placement"]
        },
        {
            "file": profiles_relative,
            "pointer": "/guest_resource_profiles/G6",
            "value": profiles["guest_resource_profiles"]["G6"]
        }
    ],

    "implementation_refs": [
        "physical_model/manifest_adapter.py:normalize_guests",
        "physical_model/resource_models/electrical.py:evaluate",
        "physical_model/resource_models/cooling.py:evaluate"
    ],

    "effect_on_results": (
        "Allows conditional G6 power, cooling, placement, "
        "mass and compute evaluations. Does not establish "
        "real-world installation or admission feasibility."
    ),

    "resolution": (
        "Replace demonstration values with verified hardware "
        "specifications and re-evaluate the complete mission envelope."
    ),

    "sensitivity": None
}

register["assumptions"] = [
    item for item in register["assumptions"]
    if item["id"] != "G6-DEMO-01"
]

register["assumptions"].append(assumption)

# Track critical information still missing from G6.
unresolved = {
    "id": "U08",
    "topic": "G6 unverified hardware and fire-control behavior",
    "source_refs": [
        {
            "file": g6_relative,
            "pointer": "/documented_unknowns",
            "value": g6["documented_unknowns"]
        }
    ],
    "action": (
        "Verify physical installation, actual resource demand, "
        "safety timing, fire-detection triggers and mode transitions."
    )
}

register["unresolved_inputs"] = [
    item for item in register["unresolved_inputs"]
    if item["id"] != "U08"
]

register["unresolved_inputs"].append(unresolved)

register["title"] = "VesselOS assumption register — G1 through G6"

# Keep existing audit-summary counts consistent.
register["summary"]["assumption_or_scenario_records"] = len(
    register["assumptions"]
)

register["summary"]["source_rule_records"] = len(
    register["source_rules"]
)

register["summary"]["unresolved_input_groups"] = len(
    register["unresolved_inputs"]
)

rows = register["assumptions"] + register["source_rules"]

register["summary"]["classification_counts"] = dict(
    Counter(row["classification"] for row in rows)
)

with open(register_path, "w", encoding="utf-8") as file:
    json.dump(register, file, indent=2, ensure_ascii=False)
    file.write("\n")

print("G6 simulation assumptions registered successfully.")