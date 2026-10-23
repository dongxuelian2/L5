# L5 / TripLens architecture and contracts

The workstation and external monitoring studies share evidence contracts while retaining separate process spaces. No source is converted by column position or similar signal names.

| Logical module | Implementation | Boundary |
|---|---|---|
| Data & Process Adapters | `simulation/platform.py::parse_csv`, `benchmarks/tep.py`, `rieth_independent.py`, `multimode_normal.py` | Explicit source format, ordered schema, clock, provenance; labels outside feature matrices |
| Evidence & Data Model | `l5/contracts.py` | Immutable `SignalSchema` / `ObservationBatch`, units, missing mask, sequence, operating mode, partition |
| Monitoring Engine | `benchmarks/monitoring.py`, `session.py`, `coverage.py`, temporal/adaptive/DPCA modules | Research-only sessions enforce normal fit/calibration roles, chronological disjointness, schema compatibility and fresh sequence state |
| Diagnosis Engine | `simulation/platform.py::diagnose` | Observations only; no simulator Config/fault label argument; support, contradiction and unavailable evidence remain separate |
| Decision & Counterfactual Engine | `fit_hypothesis`, `simulate`, `interventions` | Relative one-second clock, exact observation window, inclusive +20…240 search; physical pressure determines trip status |
| Investigation Workstation | `src/components`, `src/lib/comparison.ts`, `src/lib/platform.ts`, `server.py` | Existing React interaction; time-matched prefixes; recovery withheld before +240s; API schema version remains compatible |
| Benchmark & Verification | `benchmarks/run_suite.py`, `verify_reports.py`, `simulation/verify_artifacts.py`, `tests/`, Actions | Pinned sources, frozen protocols, separate software/numerical regressions and external research reports |

## Signal spaces

| Schema | Width | Clock | Interpretation |
|---|---:|---|---|
| `triplens-synthetic-18-v2` | 18 | seconds, 1 s | Explicit synthetic engineering keys and units; accepted by current diagnosis/CSV API |
| `tep-classic-52-v1` | 52 | 180 s | Original XMEAS(1…41), XMV(1…11) order; Braatz/Rieth source provenance is retained in each report/run identity |
| `thufdd-tep-native-53-v1` | 53 | source sample index | Original columns 0…52; physical meanings/units and seconds remain unknown; last 28 raw disturbance columns excluded |

The legacy six-channel PROCESS 01 demo remains a separate reduced-order model. Its results do not validate PROCESS 02 or external TEP data.

`ObservationBatch` copies caller-owned lists into immutable tuples and preserves missing values. `ResearchSession.fit` accepts only explicit normal-fit and normal-calibration partitions. Overlapping/reversed partitions from the same sequence fail. Scoring rejects schema changes, missing observations and sequence gaps unless an explicit observation policy handles them. Coverage evaluation uses its original Boolean observation mask; imputation never overrides abstention, and a temporal monitor restarts after abstained intervals.

The current CSV/API contract uses documented synthetic keys and seconds. Duplicate headers, ragged records, malformed quoting, nonfinite values and unsorted timestamps fail with a client error. Existing requests remain valid. An explicit foreign `signalSchemaId` is rejected instead of mapped into synthetic channels.

## Causality and decision scope

Snapshots and comparisons select their observation prefix before reading diagnosis. Recovery and similarity remain unavailable at early cutoffs. Fitting rejects a cached diagnosis from a different window, uses elapsed time rather than absolute timestamp indexes and refuses unsupported cadence/horizon. Numerical error is evaluated only on supplied observations; future simulated samples do not enter the fit objective.

Simulation branches preserve their fitted baseline prefix before action. They do not assert a perfect observed prefix when the fitted model differs from the measurements. `physicalPeak` and the physical trip flag retain the safety calculation; rounded display peaks must not replace them. Missing observations break alarm continuity without generating a normal-return event. Durations use timestamp seconds and do not bridge unobserved gaps.

Pressure-intervention rankings are withheld when the fitted physical baseline remains below its pressure limit. Other reported rankings are conditional simulator comparisons, without predictive intervals or external intervention validation. Parameter/model uncertainty remains open research, not an operational guarantee.

## Verification and operation

`npm run check` runs Python tests, frontend export tests, TypeScript/Vite, and complete numerical regeneration checks. The Python runner chooses `.venv` when present and forces UTF-8 across platforms. CI checks Linux and Windows. The separate external-data workflows run on relevant source/protocol changes or manual dispatch, cache fixed inputs, revalidate hashes and cancel obsolete runs; ordinary UI/docs changes do not trigger all external downloads.

The reference suite preserves all eleven study configurations and their logs. Numerical snapshots capture audited thresholds, workload, coverage, fold/seed summaries and negative outcomes with float tolerance. They check software drift; repeatedly consulted simulator data provide no new independent evidence. Raw third-party datasets remain outside Git and report artifacts.
