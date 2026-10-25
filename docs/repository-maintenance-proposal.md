# Repository maintenance proposal

## Goal

Keep L5 easy to extend, review and reproduce as a long-running industrial analysis and research project. Reduce duplicate artifacts, one-off verification machinery, unnecessary persistence layers and oversized pull requests.

## Working principles

- **Keep product functionality primary.** Prefer shared data models, algorithm interfaces and reusable workflows over feature-specific wrappers and audit systems.
- **Version source and small reproducible inputs.** Keep application code, tests, documented protocols, essential example fixtures, dependency locks and numerical golden references where tests actually read them.
- **Generate bulk results outside Git.** Store complete experimental runs, detailed reports, local databases and transient verification receipts under ignored output paths or CI artifacts. Preserve concise research findings, declared protocols and exact commands in versioned documentation.
- **Preserve relevant integrity checks.** Official dataset checksums and persisted-source identities have real data-integrity purposes. Remove duplicated hash fields and repeated snapshots after tracing their consumers; avoid replacing scientific reproducibility with cosmetic tidiness.
- **Keep PRs cohesive.** Each PR should have one main purpose, an intelligible review diff and the tests needed for that purpose. Distinguish algorithm changes from product changes and regenerated artifacts.
- **Document what works.** README describes current user capabilities; research reports describe methods, results and limitations; detailed test logs belong in CI output.

## First audit targets

| Paths | Present role | Review action |
| --- | --- | --- |
| `src/data/platform.json`, `src/data/scenario.json` | Bundled TripLens example loaded by the front end | Keep working examples; evaluate storage/size only after checking runtime use |
| `benchmarks/numeric_reference.json` | Golden numbers read by `benchmarks/verify_reports.py` | Retain regression coverage; evaluate smaller projections later |
| `benchmarks/rieth_sources.json`, `examples/tep/*protocol.json` | Dataset identity and frozen experimental protocols | Retain |
| `examples/tep/*_summary.json`, `*_per_run.csv`, `fault3_summary.json` | Published derived study outputs | Move bulky detail to regenerated output/CI artifacts only after updating readers, links, and result browsing; keep essential summary in docs |
| `docs/verification/*.json`, one-off integration notes | Historical execution receipts | Assess consumers and consolidate, keeping durable conclusions and links to runs |
| `video/triplens-pitch.mp4` | Showcase asset | Decide whether release assets are a better distribution location |

## Execution sequence

1. Inventory tracked artifacts, their writers, imports, tests and documentation references.
2. Classify each artifact as source, runtime fixture, golden reference, reproducible research summary, or generated output.
3. Apply repository organization and ignore rules in small reviewable commits; update generation and publication paths together.
4. Add a concise contribution guide and PR template with a purpose, code/data changes, and relevant verification.
5. Run normal CI, example generation checks and the applicable external-data workflow before removing an artifact used by a study.
6. Report actual removals, reduced repository/review footprint and retained regeneration commands.

## Reference practices

- [pandas contribution guide](https://pandas.pydata.org/docs/development/contributing.html): reviewable PR scope and descriptive change categories.
- [scikit-learn developer guide](https://scikit-learn.org/dev/developers/contributing.html): focused development workflow and review.
- [GitHub repository-size guidance](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github): repository contents and bulky generated assets.

This document establishes the cleanup scope. Functional changes and artifact removal are pending review.
