# Process Safety workspace

Open **Process Safety** inside a Workspace and select a Dataset. To use a simulated process, save a run from **Models & Scenarios** to the Workspace and select the resulting Dataset. Check engineering units in **Signals** before setting limits on imported data.

1. Add a named constraint and choose its signals by their catalog identity. A value constraint can have an upper limit, a lower limit, or both. Use a rate constraint for signed or absolute change per second. A relationship compares a weighted sum of compatible signals to its boundaries. Use the equipment field to identify the applicable operating envelope.
2. Add warning boundaries inside the critical boundaries. Set a maximum observation gap, a critical dwell time, and a clearing hysteresis as needed. Save the definitions as a named configuration to reuse them. Editing the configuration creates a new revision.
3. Evaluate the history and select a constraint to inspect the measurement, boundaries, margin and intervals. With a raw coupled-tank Dataset, enable a forecast and choose the observation cutoff, horizon, sampling step, and future input assumptions. Configure uncertainty ranges and a seed to evaluate sensitivity.
4. Save an assessment to retain the source clock, catalog units, configuration revision, observations, assumptions, scenarios, and results. Reopen it from the Workspace, download JSON, constraint-series CSV, or a Markdown report, and attach individual intervals to an existing Incident. A predicted interval appears in the Incident's recorded evidence with its observation cutoff and forecast origin.

## Constraint semantics

For a value or relationship \(x\), the lower margin is \(x - L\) and the upper margin is \(U - x\). The displayed margin is the smaller configured margin. A negative margin is a raw threshold breach. Equality at a critical boundary has zero margin. Rates use consecutive valid measurements and their elapsed seconds, with temperature rates expressed as temperature differences per second. A relationship converts its terms to a common unit before applying coefficients. For example, a tank level of 2.1 m against a 2.5 m maximum has 0.4 m of upper-limit margin.

All timed rows enter the historical evaluation. A missing, unobserved or numerically invalid measurement leaves a gap in the constraint evidence. Acquisition gaps split continuity, as do duplicate timestamps for purposes of rate and dwell. The default maximum gap follows the Dataset cadence. Relationships use one aligned Dataset clock. Use **Transformations** to prepare a common clock and units when a relationship needs signals from different sources. Safety evaluation uses the source observation mask when a transformed Dataset carries one.

Unlabeled signals support single-signal limits in their recorded units (blank or `1`) and rates in recorded units per second (`1/s`). Assign units in the Signal Catalog before converting unlabeled measurements or using them in a relationship.

The raw evidence retains a single breached sample even when a configured dwell does not confirm it. Dwell is elapsed time across consecutive observed breaches. Hysteresis is the recovery margin required to clear an active state. A two-sided constraint requires a common recovery range. Historical durations measure spans between observed endpoints, so an isolated breach can have zero duration. Sample coverage and connected time coverage report how much evidence was available.

## Coupled-tank forecast

The forecast initializes from a synchronized measured row at or before the cutoff. The row must provide both measured tank levels and the pump and valve inputs in the simulator's native scales. A stale, missing, duplicate or physically inadmissible row can make the forecast unavailable. A short gap between the last measurement and the cutoff can be modeled by holding the observed inputs. The future path then holds those inputs or applies explicit fixed overrides. The forecast uses the coupled-tank mass balance and the existing conservative, positivity-preserving SSPRK2 integrator. It uses declared physical coefficients and optional disturbance assumptions. Compare measured and modeled inlet flow at the observed pump command, and use an explicit pump capacity override to explore a persistent loss of capacity.

**Time to Constraint Violation (TCV)** is elapsed time from the forecast origin to the first predicted violation under the declared assumptions. A violation already active at the origin can have TCV zero. With zero dwell, the forecast estimates a boundary crossing by linear interpolation between adjacent valid forecast samples. With dwell, confirmation is at a forecast sample, with applicable policy state carried from the causal observed prefix. No-crossing results refer to the selected horizon. TCV is a trajectory-based operating metric. Remaining Useful Life (RUL) describes degradation-related equipment life.

The uncertainty calculation independently samples uniform values within the entered additive ranges. A coefficient fraction is relative to the nominal value. Level ranges perturb the measured initial levels and can represent measurement error. The one-at-a-time endpoint results describe the effect of each range on minimum margin with the other settings held nominal. The reported crossing fraction uses evaluated random scenarios for that constraint, and the report retains the number of unavailable scenarios. The outputs describe the sampled trajectories and their assumptions. They provide engineering analysis for offline data and simulation.

## Coupled-tank benchmark

```bash
node scripts/python.mjs -m benchmarks.safety_tanks
```

The benchmark uses fixed scenarios and evaluates the same causal forecast at several observation cutoffs. It compares against retrospective crossings from the simulator, including physical levels and actual spilled volume in the overflow case. The output reports observation classification, crossing-time error for matched forecasts, false and missed crossings, unavailable predictions, model mismatch sensitivity, and computation time. Runtime is machine-dependent.

The fixed 85 s benchmark produced 17 matched crossings, 13 missed crossings, 4 false crossings, 10 correct no-crossing results, and 2 unavailable forecasts across 46 cutoffs. The 11 matched future crossings had a mean absolute timing error of about 0.000034 s on these simulator traces. This timing statistic is conditional on detecting the crossing. The declared parameter mismatch missed all three crossings in its case, while the matching-parameter reference detected all three. The overflow case spilled about 3.62 m³. Historical classification agreed with the simulator on 97.8% of available samples. Five samples with true violations were among the eight unavailable observations.

For a short interactive demonstration, create a healthy Coupled-Tank run with a pump command of 150%, zero level noise, and otherwise default physical parameters. Save the run as a Dataset, configure a 1.60 m upper limit for Tank 1, then forecast 30 seconds from time zero with hold inputs and a 0.2 s output step. Tank 1 starts at 1.5625 m with a margin of 0.0375 m. The forecast gives a TCV of 2.584 s and a minimum margin of −0.302 m. Compare the predicted crossing with the historical violation and vary the pump assumption to inspect the effect on TCV.
