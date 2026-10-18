> **Unified VesselOS note:** Guest manifests come from `data/guests/`, physical host
> capacities from `physical_model/data/ship_specs.json`, and synthetic profiles from
> `physical_model/data/resource_profiles.json`. The optimizer and dashboard use
> `governor/integration.py` to synchronize common inputs. See `INTEGRATION_README.md`.
>
> The original standalone team's recorded outputs and legacy solver tests reflect
> older assumptions. Re-run them with canonical physical inputs before using results.

# Resource Governor — Scenarios A, A′ and B (G1–G5)

Maritime Dual-Use Hackathon · Track 03 Software-Defined Vessel. Deterministic decision engine for the five
Annex B guests: admits, places or refuses a guest against all eight resource classes on the mission envelope
(A, A′), and arbitrates right of way and degradation at sea (B) — every decision in one sentence built from the
constraint that bound it.

## Run

```bash
pip install -r requirements.txt
make demo        # A (jury card G4), one jury override, A′ at crew 6/0, B under survey and rescue priority
make test        # 34 contract tests (Annex arithmetic, verdicts, priority swap, B timing, determinism)
make results     # results/RESULTS.md: default sets × 4 priority files, 15 A/A′ cases, 6 B runs
make account     # docs/PHYSICAL_ACCOUNT.md from the tags in config/

# Scenario A: jury card + one number changed (in memory only)
python -m governor.cli admit --candidate G4 --priority rescue \
    --set card.G4.resources.power_modes.charging_initial.power_kw.nominal=70
# Scenario A′
python -m governor.cli admit --candidate G4 --state location=at_sea crew=0
python -m governor.cli admit --scenario scenarios/A_prime_drone_swap.yaml --state crew=6
# Scenario B: jury picks the priority file, the crew level, or changes any number
python -m governor.cli b --priority rescue --crew 6
python -m governor.cli b --priority survey --set scn.timeline.1.reserve_kw=60
```

## Dashboard

```bash
make setup        # once (installs Flask too)
make dashboard    # → http://127.0.0.1:5050   (PORT=5060 make dashboard to change)
```

Eight gauges (power, cooling, deck, mast, mass, data links, compute, response time) and three tabs:
A (port admission), A′ (under way: crew, speed, deck, drone swap), B (right of way; scrub/play the 90-min timeline).
Grey needle = installed set alone, white = after the decision, red = over budget. Knobs are in-memory jury overrides.
"Search all G1–G5 trios" ranks the starting sets for the priority file; "use" loads one as the installed set.
`dashboard/app.py` only calls `classify_admission`, `right_of_way` and `search_defaults`; it decides nothing.

## Architecture

```
guests/G1..G5.json + guest_schema.json ─► validate_manifest() ─► load_guest_data() ◄─ config/guest_overlays.yaml
config/ship.yaml (Annex A, envelope) ──► load_ship_budget()        config/priorities/*.yaml (swappable input)
                                              │
        ┌─────────────────────────────────────┴───────────────────────────────────┐
  A / A′ · D1 + D2 (governor/model.py, admission.py)            B · D3 + D4 (governor/rightofway.py, config/ops.yaml)
  CP-SAT: installed · mode (normal + degraded) ·                minute-step simulator: ship state machine (A.6),
  position · line · interlocks; each capacity                   G3 survey/charge cycle, G4 battery/landing/charge,
  group behind an assumption literal                            event timeline (scenarios/B_right_of_way.yaml)
  lexicographic: U → U_degraded → −crane min →                  D3: conflicts from card requirements → hard
  −interlocks → margin → placement                              deadlines → simulate each option → max Σ w·cap-min
  infeasible → every class failing alone, else                  D4: throttle/defer before shed, least weighted
  minimal core                                                  capability per kW first; protected loads untouched
  YES · YES-IF · NO · NOT-NOW + sentence + ranked               rationale + cost to the loser + D4 sequence with
  displacement + alternatives + stress states                   timestamps + what every guest got
  independent evaluator re-checks every plan                    crew rule (D5): confirm / automatic / impossible
```

## Decision classes and what each optimises

| Class | Component | Objective / rule |
|---|---|---|
| **D1 Admission** | `admission.classify_admission()` | Feasible in every envelope state; max weighted capability kept (Σ w·c), then capability with one genset down, then least crane time, fewest operating rules, largest tightest margin. Verdict + binding class + ranked displacement list + "holds with one genset down?" + net-value warning. |
| **D2 Placement** | `model.add_placement_constraints()`, `admission.placement_options()` | Same objective; ties → preferred positions and most remaining margin. Every allowed position of the candidate reported as chosen / rejected (why) / impossible (why). |
| **D3 Right of way** | `rightofway.right_of_way()` | Hard constraints first (battery deadline, A.6 transitions, crew confirmation); then max U = Σ weight × capability-minutes over 90 min, with D4 effects simulated. Rationale + cost to the loser. < 0.02 s. |
| **D4 Degradation** | `rightofway.shed()`, `model.add_mission_envelope_constraints()` | Throttle/defer before shed, cheapest weighted capability per kW first; never the D3 winner's critical load, a running non-interruptible charge, or a safety-critical guest. First command 0.1 s, then every 2 s; restore with hysteresis. |
| D5 Crew rule | `config/ops.yaml crew_policy` | Human confirms a contested decision unless the delay would break a hard deadline or nobody is aboard → automatic. |
| D6 Physical Account | `docs/PHYSICAL_ACCOUNT.md` | Generated from tagged config lines (file:line), findings on the PDF arithmetic, closing question. |

## Key results (results/RESULTS.md)

* **Defaults (A)** — survey: G1+G2+G3 (16/16); rescue: G2+G4+G5 (25/25); patrol: G1+G2+G4 (20/20).
  G2+G3+G4 (10.04 t) and G2+G3+G5 cannot be starting sets.
* **A, Annex set G1+G2+G5** — G4 YES; G3 YES-IF remove G5 (mass, stability, deck all bind).
  Jury sets G4's charge to 70 kW → cooling binds (135 kW > 120 kW at 30 °C) → G5 to low power.
* **A′** — every Annex card has a port-only component → NOT-NOW with the next-port verdict; crew 0 → logical
  levers only; a drone swap at sea gets the window conditions and minutes to establish them.
* **B** — survey priority: drone lands at min 19 (deadline 20), survey holds depth, leg re-run, nothing shed.
  Rescue priority: survey suspended, drone charge protected, UUV recovered; when its 25 kW charge meets the
  drone's 35 kW after the trip (111 kW > 100 kW) G5 drops to low power, restored at min 39.

## Limitations

* B fleet (G2+G3+G4+G5) is not admissible under A.3/A.4; B skips admission as the PDF narrative does.
* With the card loads, nothing must be shed at the min-12 trip (55 kW of 100 kW); the order is logged and executed
  when the load rises. The jury can tighten the reserve (`--set scn.timeline.1.reserve_kw=60`).
* No ≤60 s peaks exist on the cards, so the peak and cooling-inertia rules are coded but never exercised.
* Compute per guest is assumed (cards leave it null); pooled, no per-node packing.
* Data links budgeted at the best end of A.5; emission silence and SATCOM 2 Mbit/s reported as stress states.
* Stern-ramp craft limit not checked (no vehicle-only mass on the G3 card). G6 not yet defined by the team.

## With another week

Team-defined G6 card; Open-Meteo seawater temperature to replace the 30 °C worst case on a known route; a single
screen with the eight gauges driven by `rightofway` rows; per-node compute packing; probabilistic weather windows
for A′.
