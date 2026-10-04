# TripLens

**Follow the evidence. Change the outcome.** An incident investigation and decision workstation for continuous processes.

[中文](README.md) · [Run locally](#run-locally) · [Computation and scope](#computation-and-scope) · [Adjustment notes](docs/adjustment-notes.md)

A modern terminal aesthetic in the browser: character animation, fine process graphs, moving propagation paths, inspectable evidence and numerical intervention search. The workflow is **Detect → Compress → Investigate → Verify → Intervene → Learn**.

![Investigation workspace](docs/investigation-v2.png)

[Recovery search](docs/recovery-v2.png) · [History and verification](docs/learn-v2.png) · [Original incident replay](docs/workstation.png)

## Current capabilities

- **INVESTIGATE:** 12 incident sessions, 18 observed channels and 14 material, energy, control and feedback paths. Diagnosis receives observations, never scenario labels. Each hypothesis exposes supporting, contradictory and unresolved evidence, signed score components and recommended next measurements.
- **Process versus control:** two loops expose SP / PV / OP / actuator feedback / output limit. Independent pressure and temperature channels help distinguish process changes from sensor faults. Frozen, missing, stale or extreme-step evidence cannot earn strong process-causality credit.
- **Time boundaries:** +40 / 70 / 110 / 180 / 240-second snapshots are separately recomputed from available samples. Earlier windows cannot display full-window counterfactuals or historical similarity.
- **Intervention search:** cooling bypass, feed reduction, backup pump, setpoint adjustment, emergency cooling, controlled shutdown and combined actions. Each session fits its leading hypothesis and evaluates **1,547 branches**, enumerating every second from +20 to +240. All safe intervals, latest recoverable starts, pressure margins, production loss, quality loss and additional cooling consumption are retained. Drag the start time to inspect successful and unsuccessful branches.
- **Alarm compression:** separate activations, reannunciations, returns, unique conditions and process groups. Inspect flood segments, persistent/fleeting/chattering conditions and a filterable raw journal. Rationalization suggestions preserve independent safety alarms; they do not execute suppression.
- **Investigation audit:** expand exact structured inputs and numerical outputs. A local deterministic investigation policy operates behind a reserved interface for model-authored tool requests.
- **LEARN:** similar observed fingerprints, alarm rationalization, a 36-variant internal verification matrix, and completed investigations with operator notes retained as browser-local JSON and exportable.
- **CSV replay analysis:** imported time-ordered signals use the same blind diagnosis, quality checks, alarm analysis and tool audit. Missing channels remain unresolved. Imports require the local Python service.
- **RCA dossiers:** Markdown / JSON exports include the summary, detection and alarm times, controllers, propagation, hypotheses and counterevidence, counterfactuals, procedure prerequisites, similar sessions, health and open questions.
- **LIVE / REPLAY / LAB:** the original cooling-valve sequence, chapter navigation, signal inspectors, correlation matrix and CUSUM remain available. That six-channel PROCESS 01 model and the new two-controller PROCESS 02 model are computed separately.

## Run locally

Requires Node.js 20.19+ or 22.12+, npm, and Python 3.10+ for regeneration, tests and the optional backend. No third-party Python packages.

```bash
npm ci
npm run dev
```

The app opens INVESTIGATE. The static experience needs no API key or external network; calculated artifacts and fonts are bundled.

```bash
npm run generate  # recompute both models, 12 sessions and the verification matrix
npm run check     # Python tests, TypeScript checking and production build
npm run preview   # static preview, port 4173 by default
```

For the complete experience including CSV imports:

```bash
npm run build
python3 server.py   # http://127.0.0.1:8787
```

During development run both `python3 server.py` and `npm run dev`; Vite proxies `/api` to local port 8787.

Suggested route: **Investigate → choose a session / observation time → Interventions → Tool audit → Alarm journal → Save to memory → Learn**. The original animated sequence remains under **Live incident → Run sequence**.

Shortcuts: `Ctrl/⌘ K` command palette; `1/2/3/4/5` Live / Investigate / Learn / Replay / Lab; `Space` play/pause in Live / Replay; `R` open Live and restart; `?` field guide; `Esc` close dialog.

## Computation and scope

`simulation/platform.py` uses only the Python standard library. The coupled reduced-order model includes output saturation and rate limits, actuator response, transport delay, cooling, feed, thermal inertia, pressure, separation and feedback. Physical pressure is separate from measured pressure: a faulty transmitter alarm is not a physical threshold crossing.

Fault families: cooling-valve sticking, feed-valve sticking, cooling-water degradation, feed-composition disturbance, reaction-rate disturbance, pump degradation, separator restriction, pressure bias, temperature drift, pressure freeze, controller output-limit changes and control-loop oscillation. Parameters include severity, onset, delay, noise, controller response, operating point and seed.

Detection fits median/MAD baselines on the first 20 stable samples, with minimum engineering scales, and confirms four consecutive observations beyond six scales. The baseline remains fixed within the window; it is not adaptive. Scores combine signed engineering evidence and a small topology term; **they are not calibrated probabilities**. Next-observation priorities are explainable heuristics, not calibrated information value.

Counterfactuals do not receive ground truth: diagnose the observed window, then grid-fit onset and severity for the leading hypothesis. Interventions run on that fitted model and preserve its pre-action prefix. Safe means **physical pressure never crosses 3,050 kPa within the 240-second model horizon**, not indefinite safety or a plant actuation recommendation. Recommendations compare each action at its own latest safe start by pressure margin, production loss or recoverable time; no opaque overall optimum is asserted.

The PROCESS 02 cooling-valve session produces **312 events → 6 conditions → 3 process groups**. Its fitted unmitigated model crosses at +109 seconds. The latest safe cooling-bypass start is **+101 seconds**; emergency cooling remains effective through **+103 seconds**. Different control behavior means these values must not be mixed with the original 656-event PROCESS 01 model.

Internal checks cover **12 families × 3 parameter variants = 36 fault windows**, plus three healthy windows. Current Top-1 / Top-3 are 36/36, median detection delay is 3 seconds and healthy windows flagged are 0/3. These are same-simulator rule regressions, **not independent dataset accuracy**. No Tennessee Eastman benchmark or real factory connection has been evaluated. MQTT / OPC UA, general natural-language SOP import, real Nemotron planning and an independent public benchmark remain future integration work.

## Data and model interfaces

CSV uses timestamps in seconds under `t`; other columns use the signal keys documented in `src/lib/platform.ts`. Download a complete example from the UI. Supply 25–2,000 rows including 20 stable baseline rows. Blank values are missing; duplicate or decreasing timestamps, nonfinite values and unknown columns are rejected.

```http
POST /api/replay
Content-Type: application/json

{"csv":"t,valve,flow,...\n..."}
```

Structured tools require no orchestration framework:

```http
POST /api/investigate
Content-Type: application/json

{"rows":[...],"calls":[{"tool":"inspect_signal_window","args":{"signal":"valve"}},{"tool":"compare_hypotheses","args":{}}]}
```

Accepts 1–16 allowlisted requests: signal window, change point, controller, downstream paths, alarm history, hypothesis comparison, SOP alignment and next measurement. Only signal-window inspection accepts a `signal` parameter; other tools use empty argument objects. Omitting `calls` runs the default policy. Results come from the observations; a model cannot override numerical values or submit fault labels.

The original six-channel analyst retains `POST /api/analyze` and a server-side Chat Completions compatible adapter. Local structured evidence is the default; an external model is not configured. To connect one, set the Python server environment:

```bash
export TRIPLENS_MODEL_ENDPOINT='https://your-provider/v1/chat/completions'
export TRIPLENS_MODEL='your-model-id'
export TRIPLENS_MODEL_API_KEY='your-secret'
python3 server.py
# Another terminal: VITE_ANALYST_PROVIDER=http npm run dev
```

`.env.example` is documentation; Python does not load it automatically. Credentials stay server-side and must never use `VITE_` variables. The adapter is verified with a loopback fixture, with no claim of real Nebius / NVIDIA inference.

## Structure

```text
src/components/PlatformWorkspace.tsx  Investigation, recovery, alarms and learning
src/components/platform.css           Terminal visuals and responsive layout
src/lib/platform.ts                   Contracts, RCA exports and browser memory
src/data/platform.json                Rebuildable sessions, branches and checks
simulation/platform.py                Blind diagnosis, control loops, search and tools
simulation/test_platform.py           Time, quality, branch and diagnosis validation
simulation/generate.py                Original six-channel incident model
server.py                             Standard-library HTTP, CSV and model adapter
```

React + TypeScript + Vite + Motion + Tailwind CSS; native Python + JSON. No Docker, database, LangChain, ML framework or 3D engine.

MIT License.
