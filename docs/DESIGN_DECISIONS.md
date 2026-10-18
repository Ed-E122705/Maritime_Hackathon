# Design decisions

Three sources, three levels of authority:

| Source | Authority | How we treat it |
|---|---|---|
| Challenge PDF (Annex A/B, D1–D6, A.6–A.11) | **Hard** | Every value tagged `[A.x]`/`[B Gx]` is used as given. Ranges are resolved to the conservative end unless noted in the Physical Account. |
| `guests/guest_schema.json` | Rule, with judged exceptions | All six cards validate. Exceptions are listed below — data the schema cannot express lives in `config/guest_overlays.yaml`, never by bending the cards. |
| `docs/Whole_model.docx` | Starting rule, may be overridden for a better result | Names and structure kept. Deviations below, each with the reason. |

## PDF compliance map

| PDF requirement | Where | Status |
|---|---|---|
| Judge against the mission envelope, not the pier (A.10) | `loader.load_ship_budget()` — lowest reserve of slow/cruise bands, 30 °C water, genset loss | ✅ pier state shown, never used |
| State whether it holds with one genset down | `admission._degraded_statement()` | ✅ every verdict |
| Name the binding resource class, one sentence, live numbers | `model.binding_groups()` + `admission.describe_group()` | ✅ no canned strings |
| YES-IF: ranked list of what is displaced or throttled + capability lost | `admission._actions()`, `alternatives()` | ✅ |
| NOT-NOW: conditions and time of the next window (A′, A.11) | `admission.at_sea_decision()`, `_swap_decision()`, crane-time NOT-NOW | ✅ |
| Crew 0 → logical reconfiguration instead (A′) | `admission._logical_levers()` | ✅ |
| Power–heat coupling 1:1, cooling falls with seawater (A.2) | `model.add_cooling_constraints()` | ✅ |
| Two mission lines, 150 kW each, line can saturate while total does not (A.1) | `model.add_power_constraints()` | ✅ |
| Sustained draws are not peaks (A.1) | windows → load cases | ✅ |
| Bay 1: one 20-ft or two 10-ft if neither needs the bay clear (A.3) | `model.add_placement_constraints()` | ✅ |
| Mast: 1 free slot, ≤60 kg, ≤0.6 m², air-cooled ≤2 kW (A.2/A.3) | `loader.load_guest_data()` static checks + slot count | ✅ |
| Mass 10 t, stability 12 t-eq with ×1 / ×1.2 / ×3 (A.4) | `model.add_mass_constraints()` | ✅ |
| Data links, SATCOM shared, zero in silence (A.5) | `model.add_data_constraints()` at the best end of A.5; `admission.comms_stress()` reports the 2 Mbit/s low end and emission silence | ⚠️ best-case budget, worst cases reported |
| Compute 80 % allocatable, no hot-add (A.7) | `model.add_compute_constraints()` | ✅ |
| 30 s admission ceiling (A.8) | measured per verdict (`elapsed_s`), solver time limit | ✅ 0.05–0.8 s |
| Safety-critical never shed automatically (B.0) | never removed (A); never in a D4 shed order (B) | ✅ no Annex card sets the flag; a test flips it on G5 |
| Part-of admitted and shed as one (B.0) | one `installed[]` per assembly | ✅ |
| Priority file is an input, ≥ 2 sets | `config/priorities/*.yaml` (4 sets) | ✅ swap changes outcomes (tests) |
| Deterministic, replayable | single worker, fixed seed; replay test | ✅ |
| Stern ramp one craft ≤ 5 t (A.3) | not checked — G3 card has no vehicle-only mass | ⚠️ documented unknown |
| Physical reconfiguration only per A.11 | port: anything; at sea: flight-deck/ramp swaps in a window; crew 0: nothing | ✅ |
| One invented card | **not yet** — team decision pending; the empty `guests/G6.json` from the repo is ignored by the loader | ⏳ |

## Deviations from Whole_model.docx

| docx | What we did | Why |
|---|---|---|
| `power_line_selected[i,l]` is a free decision | Line follows from position via a fixed wiring map (`ship.yaml power.wiring`) | Cabling is the ship's, not the guest's. Making it free let the solver re-cable in its head; the big-M version was also 50× slower (8 s vs 0.02 s per solve). |
| Single objective `max U = Σ w c x` | Lexicographic: U_normal → U_degraded → −crane minutes → −interlocks → tightest margin → preferred placements | Keeps the docx objective first; the extra levels break ties honestly (robustness to genset loss, least disruption, D2 "leave future guests least constrained"). |
| One `mode_selected` per guest | One mode set for the normal envelope and one per degraded state | Lets one model answer "does it hold with one genset down?" with the shedding D4 would do, without letting a fault *raise* any guest's mode. |
| G2 winch and G3 charge "not freely interchangeable modes" | Modelled as sustained windows that replace the full-mode draw; every combination that can coincide is a load case unless the governor adds an interlock | Implements the docx warning exactly; interlocks become explicit operating rules in the verdict. |
| G4 Normal 10 kW | Kept (follow-up charge treated as continuous) | Conservative; recorded. |
| G3 Standby 1 kW as the normal mode | Normal (surveying) = 2 kW ship-side | The G3 card says not to assume standby applies while deployed. |
| `N_GUESTS = 6` (G1–G6) | G1–G5 only | Team instruction: G6 is not modelled until the team defines it. docx G6 parameters and the G6 survey weight are not used. |
| `MISSION_TYPE = "survey"` | Survey is the default priority file; rescue, patrol, disaster relief added | PDF requires ≥ 2 swappable sets. |
| `SOLVER_TIME_LIMIT 30 s`, seed 42 | Seed 42 kept; ≤10 s per lexicographic stage | Measured runs are < 1 s; the 30 s ceiling is checked per verdict. |
| — | Candidate must run full or low, never parked in standby | Otherwise the solver "admits" an impossible card with zero capability (found by test). |
| — | Net-value warning when an admission removes more mission value than it adds | YES-IF can be technically valid and still a bad trade under the active priority file. |
| — | NOT-NOW when only the port-call crane time blocks (with hours needed) | A crane-time limit is a "when", not a "no". |

## Schema exceptions (judged)

* **Capability per power mode, duty cycles, deferral cost, interruptibility default** — the schema has no field linking a power mode to capability retained or to a duty cycle. These live in `config/guest_overlays.yaml`, each tagged. Cards are unchanged.
* **Compute per guest** — schema allows it but every Annex card leaves it `null`; filled in the overlay (not in the cards) so the cards stay faithful to Annex B.
* **G3/G4 operational modes with `power_mode_id: null`** — valid under the schema's `oneOf` (the key is present); the overlay assigns their electrical role.
* **Hangar roof availability** — G5 says "existing hangar roof"; A.3 lists the hangar as a ship position. The roof is treated as ship structure; `hangar_roof.requires_hangar_guest: true` switches to the stricter reading.

## Scenario B design (D3 + D4)

| Topic | Choice | Why |
|---|---|---|
| Conflict detection | From the cards' `operational_modes.requirements` of G3 `surveying` and G4 `launch_recovery`, plus declared implications (`manoeuvre_freedom` → course free, noise manoeuvring) in `config/ops.yaml` | "The conflict appears not as an alarm but as two incompatible sets of conditions on the ship's state" (PDF). No hard-coded pair. |
| Hard constraints first | Battery < 20 % → land within 12 min (G4 card); A.6 transition times (speed band 5 min, course settle 3 min, go quiet 4 min, deck clearing by crew level); landing 2 min (assumed) | An option that misses the deadline is rejected before the priority file is consulted (unless `allow_asset_loss`). |
| Options | wait for leg end · recover now then resume (re-run leg) · recover now and suspend survey | The three courses of action the PDF demo describes; each is simulated, not scripted. |
| Choice | Highest U = Σ weight × capability-minutes / 90 min, D4 effects included | Priority file is an input; swapping it changes the outcome (tests). |
| Cost to the loser | Read from the simulation: survey minutes discarded/paused, legs completed, drone relaunch delay, probe idle | Generated from numbers, no canned text. |
| Crew (D5 rule) | Human confirms a contested decision (1 min at 14 crew, 3 min at 6); automatic if confirmation would break a hard deadline or no crew is aboard | Written-down version of the crew's common sense; same code, three crew levels. |
| D4 order | All throttles/deferrals before any shed; within each, least weighted capability lost per kW freed; protected: D3 winner's critical load, running non-interruptible charge, safety-critical guests | "Throttle to low-power modes before shedding"; "declared order"; nobody writes the sequence by hand. |
| D4 timing | First command 0.1 s after detection, 2 s between commands; restore with 5 kW hysteresis | A.8: first ≤ 5 s, full ≤ 60 s (tests). |
| B fleet | G2, G3, G4, G5 aboard as the PDF narrative states, admission skipped | Under A.3/A.4 this set cannot be admitted (13.07 t; bays) — recorded in the Physical Account. |
| Genset trip at min 12 | Reserve from the event payload (100 kW); cooling from 24 °C seawater (133 kW) | The PDF demo's numbers; the jury can change either with `--set scn.*`. |
