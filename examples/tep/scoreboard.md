# Rieth TEP · independent nine-algorithm evaluation

Fixed normal fit run 1 and calibration run 2. Eight independent test runs; 52 process inputs; 180 s cadence. Faults 1, 3, 5 were declared before scoring.

| Algorithm | Independent normal FP / 1920 | Fault 1 recall / median delay (s) | Fault 3 recall / events hit | Fault 5 recall / median delay (s) |
|---|---:|---:|---:|---:|
| robust-maxz | 0 | 0.988125 / 1710 | 0 / 0/2 | 0.165625 / 2160 |
| pca-q | 0 | 0.994375 / 810 | 0 / 0/2 | 0.155625 / 630 |
| pca-t2 | 0 | 0.98875 / 1620 | 0 / 0/2 | 0.205625 / 450 |
| ewma | 0 | 0.985 / 2160 | 0 / 0/2 | 0.166875 / 4680 |
| cusum | 0 | 0.960625 / 5670 | 0 / 0/2 | 0.81375 / 17280 |
| window-cusum | 0 | 0.981875 / 2610 | 0 / 0/2 | 0.1675 / 5220 |
| dpca-q | 2 | 0.9925 / 1080 | 0.00125 / 1/2 | 0.198125 / 630 |
| dpca-t2 | 0 | 0.988125 / 1710 | 0 / 0/2 | 0.20125 / 720 |
| adaptive-maxz | 0 | 0.988125 / 1710 | 0 / 0/2 | 0.160625 / 2250 |

Each fault cell contains two runs (1600 post-onset samples); normal testing contains two complete 960-sample runs. Recall pools TP/FN; delay summarizes detected events only. Missed events have undefined delay. Full confusion counts, precision/F1/FAR, event counts, per-run metrics, coverage, abstention, durations, errors, hashes and fixed configuration are in results.json.

- Public process simulation, mode 1 only; not plant measurements.
- Two runs per fault are descriptive and do not support population confidence claims.
- Quantile calibration on one normal run does not guarantee a held-out false alarm budget.
- Adaptive Max-Z is experimental; statistical contributions are not causal diagnoses.
