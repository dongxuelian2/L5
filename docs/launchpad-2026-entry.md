# TripLens — LaunchPad Hacks 2026 candidate brief

This historical brief preserves the original event-period scope and provenance. See [the integration audit](integration-2026-10-23.md) for current scope and verification. The consolidation does not submit an event entry.

**Status:** Entry preparation only. Registration and submission have not been completed by this repository change.

**Event:** [LaunchPad Hacks](https://launchpad-hacks.devpost.com/) · Online student hackathon · Submission deadline November 20, 2026, 5:00 PM Eastern Time.

## Project in one sentence

TripLens is a local-first incident investigation and decision-support workstation for simulated continuous-process plants: it compresses alarm floods, evaluates competing fault hypotheses from observations, audits the evidence, and tests intervention timing on a reduced-order model.

## Existing work vs. event-period work

**Prior work (before October 16, 2026):** The initial TripLens interface, PROCESS 01/02 simulator, 12 synthetic sessions, time-bounded analysis, intervention search, alarm journal, dossiers, documentation, and earlier video. These are **not** new deliverables of this hackathon.

**New functionality proposed during the event period:** A side-by-side *Compare cases* view, presenting two distinct incidents at a matched observation cutoff (+40/70/110/180/240 seconds), with observed-only diagnosis, alarm compression, evidence health, next measurements, and an exportable JSON comparison. The comparison withholds complete-window recovery information before +240 seconds.

**Before submission:** Check the Git history of this feature and accurately enumerate any further work completed within the official event window. Judges should assess the new contribution, not be led to believe the entire older system was developed during this event.

## Reproducible evaluation

Prerequisites: Node.js 20.19+ or 22.12+, npm; Python 3.10+ for the full test suite.

```sh
npm ci
npm run check
npm run dev
```

The static UI needs no paid API keys or cloud service. The optional CSV upload endpoint requires the Python server: `python3 server.py` in a second terminal. The app's comparison panel and bundled incident data work without the Python server.

### Suggested 2–3 minute video outline

1. **0:00–0:25** — State the user problem: alarm floods obscure what happened and whether any intervention window remains.
2. **0:25–0:55** — Open **Investigate**, choose a synthetic incident, explain observed signals and the leading *rule-based* hypothesis; distinguish score from probability.
3. **0:55–1:25** — Switch **AS OF** from +40s to +240s: show why later evidence must not leak into an early investigation.
4. **1:25–1:55** — Open **Compare cases**, select a second incident, compare evidence quality, alarm counts, and leading hypotheses at one shared cutoff. Download the comparison JSON.
5. **1:55–2:25** — Return to **Interventions** at +240s, adjust intervention start and show a successful versus unsuccessful modeled branch.
6. **2:25–2:50** — Mention reproducibility, limitations, and the specific contribution completed during this hackathon.

Record **a new demo** that visibly covers the comparison feature; the earlier video is historical evidence, not a demonstration of new functionality.

## Suggested submission assets

- Public repository: https://github.com/dongxuelian2/L5
- Screenshot of the new Compare cases panel at +40s and +240s (capture after build).
- Existing screenshots: `docs/investigation-v2.png`, `docs/recovery-v2.png`, `docs/learn-v2.png` (label them as pre-existing).
- A new short video accessible to judges through November 25, 2026.
- A clean description of new commits and provenance, plus an explicit AI-development disclosure.

## AI assistance, data, and safety limits

- AI coding assistance (including OpenAI tools where used) must be disclosed in the Devpost entry. The author is responsible for reviewing, testing, and explaining all submitted work.
- All bundled faults and reference comparisons are **synthetic simulations from the same reduced-order model**, not independent Tennessee Eastman or live plant measurements.
- Diagnosis uses rule-based evidence scores **not probabilities**. The internal 36-case consistency matrix is not an out-of-sample accuracy result.
- Intervention branches are conditional 240-second model predictions. The product does not control industrial equipment and is not a safety-certified decision tool.
- No Nebius / NVIDIA integration or inference is claimed.
- No real-plant data, private credentials, unlicensed media, or competition-specific integrations should be claimed without evidence.

## Submission gate

- [ ] Ensure eligibility and payment availability for the participant's residence.
- [ ] CI passes for the specific submitted commit and the app runs locally.
- [ ] The Compare cases tab functions at all five cutoffs and does not reveal full-window recovery results early.
- [ ] Capture new screenshots and a working 2–3 minute video.
- [ ] List all existing versus event-period work truthfully.
- [ ] Document any AI tools and external resources used.
- [ ] Complete Devpost registration and submission before the deadline.
