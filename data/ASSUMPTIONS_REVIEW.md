# Review of assumptions against updated ship and guest inputs

The five updated guest files now replace the previous copies. Ship specifications remain unchanged. The updated files make operation-power mappings and vehicle/drone installation targets explicit; the code consumes those fields.

## Main corrections

| Earlier behavior | Revised behavior | Why |
|---|---|---|
| G5 heat split into 44/7 kW chilled water plus 1 kW antenna | 45/8 kW on the declared bay loop | The guest explicitly says chilled-water load equals electrical load |
| G5 low-power SATCOM demand assumed 1.8 Mbps | Reserve the source maximum, 6 Mbps; actual low-mode rate unresolved | Capability fraction is not a bandwidth law |
| G1 buffering described as supported | Suppress transmission in silence; buffering remains unknown | Passive sensing does not establish data storage |
| G3 survey silently reused standby power/compute | Separate disclosed survey-power estimate and survey compute profile | Deployed power is explicitly unknown |
| Guest latency tolerances inferred from host link latency | Retain explicit demo tolerances and mark missing guest requirements | Host performance is not application tolerance |
| Updated operation/power links ignored | Validate fixed and allowed mappings, infer only explicit fixed mappings | Prevent contradictory modes |
| G4 deadline treated as a fresh ETA limit every snapshot | Check elapsed time since threshold plus ETA | A deadline must retain its origin |
| G5 roof placement required admitted G4 | Check available existing roof and drone clearance | Source permits an existing hangar roof |
| Installation time/targets ignored | Match updated record; check declared crew and time budget | Vehicle-only swap is not whole-cradle installation |
| Constants embedded in operation checks | Read guest values; move remaining inherited policy to profiles | Make unsupported host choices visible and editable |

## What remains assumed, and why

The detailed register contains 25 records. The largest groups are:

- **Guest compute demand:** CPU/RAM/GPU/storage are null in every guest. Demo profiles keep the software runnable; replace them with measured or specified demands.
- **Equipment and host geometry:** bay occupancy is declared, but most bounding dimensions and hangar/roof limits are not. Synthetic boxes only support conditional fit checks.
- **G3 deployed power/acoustic demand:** neither is provided. Explicit demo values allow sensitivity analysis without presenting them as source facts.
- **Guest latency tolerance:** response requirements are not supplied. The illustrative tolerance cannot certify application performance.
- **Resource assignment:** node, power branch and unspecified shore transport are selected scenario choices; different assignments can change the result.
- **Host interpretation:** flat reserve-by-speed values, backbone aggregation, reserve granularity and inherited operational limits require confirmation.
- **Scope:** sustained-demand snapshots omit thermal storage, full peak evidence and time-dependent mission scheduling. Unknown peaks are not declared physically zero.
- **Observed state and timing:** packaged weather/readiness/link values and execution-time numbers are synthetic. Timing remains unverified.

No arbitrary randomness or probability distributions are introduced. `ASSUMPTIONS_SENSITIVITY.json` demonstrates changes caused by explicit input changes.

## Validation and source preservation

The test suite checks updated power mappings, conflicts, mass/heat accounting, link demand propagation, declared compute overrides, installation targeting, battery timing, immutable state and deterministic output. Existing resource-boundary checks remain.

The audit checks six source-file hashes, 144 JSON-pointer values, trace IDs and generated documentation. `TEST_RESULTS.txt` records the actual run. Source hashes refer to the updated guest attachments and unchanged host file; profile records carry exact source-value snapshots.

A conditional physical PASS remains distinct from a source-supported decision. The default overall assessment remains UNKNOWN and full mission admission is NOT_EVALUATED.
