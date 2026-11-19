# L5

L5 is a local workstation for industrial process simulation, anomaly detection, and evidence-based investigation. Run Tennessee Eastman Mode 1 or a cascade of two exothermic stirred-tank reactors, or analyze recorded measurements from CSV, TSV, and read-only OPC UA acquisition.

![L5 warm-feed investigation for the stirred-tank reactor cascade](docs/l5-workspace.jpg)

## Quick start

Use Node.js 22.12+, npm, and Python 3.12+. Install GNU Fortran on `PATH` to run Tennessee Eastman. Run these commands from the repository root.

```sh
npm ci
python3 -m venv .venv
node scripts/python.mjs -m pip install -r requirements.txt
npm run build
npm run serve
```

On Windows, create the environment with `py -3.12 -m venv .venv`. The remaining commands are the same. Open [L5 on your machine](http://127.0.0.1:8787) and create or open a workspace. Records are stored locally in `data/` by default.

## Run an investigation

1. Open **Plants and runs**. The default scenario is the Tennessee Eastman reactor cooling-water inlet step. For the reactor cascade, select **Cascaded stirred-tank reactors** and keep **Warm feed to Reactor 1**.
2. Select **Run investigation**. Operating measurements appear as the simulation runs. Compare the equipment responses on a common clock, then review the alarm, diagnosis, and matched intervention.
3. Select **Export investigation report** to download standalone HTML. **Investigation findings** links to the saved analysis, experiment, incident, and operating-limit assessment. Reopen a result from **Saved runs**.

To work with your own measurements, open **Datasets** and import a CSV or TSV. The [motor cooling example](examples/data-foundation/README.md) provides three sources for practicing time alignment and resampling.

## Results and evidence

- [User guide](docs/user-guide.md) covers measurement exploration, monitoring, investigations, and specialist workflows.
- [Industrial process guide](docs/industrial-process.md) documents model equations, intervention timing, independent calibration, and numerical results.
- [Benchmark guide](docs/benchmarks.md) provides data sources, protocols, reproduction commands, and results for detector and hydraulic studies.
- [Architecture](docs/architecture.md) describes storage, provenance, and specialist input requirements.
- [MIT license](LICENSE).
