# Physical Account — Scenario A admission (D1), power + mass/stability

Every number the governor relies on, where it comes from, and the file/line that uses it.
"Annex" = docs/challenge.pdf Technical Annex A/B. "ASSUMED" = not in the Annex; our choice.
Scope of this account: Scenario A only (power, mass, stability). Cooling, positions, data links,
compute and response time are not yet modelled and will be added to this table with their own rows.

## Platform (Annex A)

| Resource class | Value used | Source / why | Where used |
|---|---|---|---|
| Electrical power reserve for the verdict | **100 kW** | A.9 degraded state, one genset down (range 90–120). A.10 says admission is judged against the mission envelope with one-genset-down assumed possible, so the degraded reserve is the budget, not the 200 kW cruise figure. | `config/platform.yaml:6` → `src/governor/resources.py:34` (`_power`) |
| Power reserve, nominal | 200 kW | A.1, informational only; printed nowhere in the verdict. | `config/platform.yaml:7` (carried in `Platform.extra`, unused) |
| Peak power (+250 kW ≤ 60 s) | not modelled | Sustained draws are not peaks (A.1). G3 charging 60 min and G4 charging 20 min are therefore continuous; G2 winch 20 kW × 5 min is a peak and is ignored here (see G2 row). | — |
| Mission power lines (2 × 150 kW) | not modelled | Line saturation is a placement (D2) question. | — |
| Mass margin | **10 t** | A.4 | `config/platform.yaml:9` → `resources.py:42` (`_mass`) |
| Stability budget | **12 t-eq** | A.4 | `config/platform.yaml:10` → `resources.py:47` (`_stability`) |
| Stability multipliers deck / hangar / mast | **1.0 / 1.2 / 3.0** | A.4 ("a 60 kg antenna costs 180 kg"). Hangar and flight deck share 1.2. | `config/platform.yaml:12-14` → `resources.py:47` |
| Heat rejection | not modelled yet | Next resource class; will be `cooling` in the registry with capacity f(seawater °C). | `src/governor/resources.py` registry comment |

## Guests (Annex B)

| Guest | Value used | Source / why | Where used |
|---|---|---|---|
| G1 power | 1.5 kW, no low mode | Card | `cards/G1.yaml:4-5` |
| G1 mass / position | 0.045 t at **mast** (×3 = 0.135 t-eq) | Card: 45 kg, free mast slot | `cards/G1.yaml:7` |
| G1 capability | patrol high, survey low, **sar low (ASSUMED)** | Card gives patrol high / survey low; silent on SAR. A passive RF sensor contributes little to rescue. | `cards/G1.yaml:9-11` |
| G2 power | **6 kW continuous**; winch 20 kW × 5 min **ignored** | Card. The winch is a 5-minute peak, not a sustained draw; Scenario A is a static admission check. It will matter in Scenario B (deck machinery while G3 listens). | `cards/G2.yaml:4` |
| G2 mass / position | 3.5 t at deck (Bay 2) | Card | `cards/G2.yaml:7` |
| G2 capability | survey high, sar medium, patrol medium | Card: "high for survey, medium otherwise" | `cards/G2.yaml:9-11` |
| G3 power | **25 kW treated as continuous**; 1 kW standby not offered as LOW | Card: charging 25 kW for 60 min after each leg, not interruptible. Admission must guarantee the vehicle can charge; a mode in which it cannot is not a mission mode. | `cards/G3.yaml:4-5` |
| G3 mass / position | 5.5 t at deck (Bay 1 whole) | Card | `cards/G3.yaml:7` |
| G3 capability | survey high, sar low, **patrol low (ASSUMED)** | Card: "high for survey, low for rescue"; silent on patrol. | `cards/G3.yaml:9-11` |
| G4 power | **35 kW treated as continuous**; 10 kW / 2 kW not offered as LOW | Card: 35 kW sustained 20 min charging. Same reasoning as G3. | `cards/G4.yaml:4-5` |
| G4 mass / position | drone 0.14 t + hangar 0.90 t, both at **hangar** (×1.2 = 1.248 t-eq) | Card: 140 kg + 900 kg, flight-deck hangar | `cards/G4.yaml:7-8` |
| G4 capability | sar high, patrol medium, survey low | Card | `cards/G4.yaml:10-12` |
| G5 power | 45 kW, **low-power 8 kW** | Card | `cards/G5.yaml:4-5` |
| G5 node mass | 3.0 t at deck (Bay 2 pref.) | Card | `cards/G5.yaml:7` |
| G5 antenna position | 0.025 t at **hangar roof (×1.2) — ASSUMED** | Card allows free mast slot *or* hangar roof. G1 is installed and holds the only free mast slot (A.3: two of three occupied), so the antenna goes to the hangar roof. If G1 were not installed the antenna would take the mast at ×3. | `cards/G5.yaml:8` |
| G5 capability | sar high, survey low, patrol low | Card: "high for rescue / disaster relief, low otherwise" | `cards/G5.yaml:10-12` |
| Low-power capability retained | **30 %** | Card G5: low-power mode = 70 % capability loss. Applied to any guest that declares `low_power_kw`. | `config/governor.yaml:13` → `admission.py:72-84` (`options_for`, `retained_fraction`) |

## Mission priorities (inputs, ASSUMED weights)

| Item | Value | Why | Where used |
|---|---|---|---|
| survey_primary weights | survey 1.0, sar 0.2, patrol 0.3 | ASSUMED. Primary mission gets weight 1; patrol slightly above SAR because the radio sensor is always useful on a cable route; SAR kept non-zero so rescue capability is never free to discard. | `config/priorities/survey_primary.yaml:4-6` → `admission.py:86` (`capability_value`) |
| sar_primary weights | sar 1.0, survey 0.2, patrol 0.3 | ASSUMED, mirror of the above. | `config/priorities/sar_primary.yaml:4-6` |
| Capability levels | high 3, medium 2, low 1 | ASSUMED linear scale for the card's words. | `config/governor.yaml:8` |
| Missing mission on a card | counts as **low** | ASSUMED default so a silent card is never scored zero or high. | `config/governor.yaml:9` |

## Decision engine (declared objective and solver budget)

| Item | Value | Why | Where used |
|---|---|---|---|
| Decision variables | per installed guest FULL / LOW / REMOVE; candidate forced FULL | Scenario A: the jury card must come aboard or be refused. | `admission.py:72`, `admission.py:150` (`build_model`) |
| Objective | lexicographic: max CI, then max MI | CI = mission-weighted capability kept / everyone at FULL. MI = free share of the tightest resource. Keep mission value first; among equal-value plans keep the most headroom. | `admission.py` stage 1/2 in `decide` |
| Verdict rule | YES if all-FULL fits; YES-IF if some plan fits; NO if candidate alone does not fit | — | `admission.py:340` |
| Binding constraint | minimal core by deletion filter; when two resources each alone refuse the card, the one **furthest over its budget** is named, the other is reported as "also over budget" | Deterministic rule instead of whichever core CP-SAT happens to return. For G3: mass +20.7 % vs stability +1.4 % → mass is binding, stability also reported. | `admission.py:211-230` (`minimal_core`) |
| Integer scale | 1000 (kW, t → milli-units) | CP-SAT needs integers; 1 g / 1 W resolution. | `config/governor.yaml:19` → `admission.py:150` |
| Margin resolution | 1/10000 | MI resolved to 0.01 %. | `config/governor.yaml:20` |
| Solver time limit | 5 s per solve (D1 budget 30 s) | Actual demo: ≤ 6 solves per decision, < 50 ms. | `config/governor.yaml:16` → `admission.py:198` |
| Determinism | num_workers 1, seed 0 | Replayable: same input → identical output (test 8). | `config/governor.yaml:17-18` → `admission.py:200-201` |
| Installed set | G1, G2, G5 | Our choice; Annex B "Jury use" expects G3 or G4 as the card. | `scenarios/a.yaml:3` |

## Cross-check against the Annex arithmetic (B, "Jury use")

* G3 with G1+G2+G5: mass 12.07 t > 10 t, stability 12.165 t-eq > 12 t-eq → YES-IF (any four exceed the margin, as the Annex says).
* G4 with G1+G2+G5: power 87.5 kW of 100 kW (12.5 % free), mass 7.61 t → YES. At cruise (200 kW) all five would fit on power, as the Annex says; they would not on mass.
* G5 + G4 + G3 charging = 105 kW > 100 kW (Annex) — reproduced when the installed set is changed to [G3, G4] and G5 is the card.

## Closing question

One more tonne of mass margin (10 → 11 t) would turn both Scenario A refusals into clean YES-IFs with a single throttle instead of a removal... but it is stability, not mass, that is nearest its budget once G3 is aboard (12.165 vs 12). The change that helps the governor most is a **second free mast position**: it removes the G1-vs-G5-antenna conflict, lets the antenna sit at ×3 without displacing a sensor, and turns the scarcest discrete resource aboard into a schedulable one.
