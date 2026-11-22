# L5 repository rules

Keep a file when it directly serves a running feature, a reproducible numerical result, installation, or necessary maintenance. Remove superseded paths, duplicate implementations, unused assets, and one-off machinery after checking their callers.

- Use English for source, UI, reports, documentation, and project metadata. Preserve original user input and source data.
- Describe what the software does, its measured results, and its operative limits in concise engineering language. Delete defensive and repetitive prose.
- Organize the product around complete user workflows. Minimize navigation, repeated selections, configuration, and context loss.
- Keep the executable plant, data, detector, experiment, incident, and reporting paths coherent. Share code across features when the same invariant applies.
- Keep real numerical checks, data compatibility checks, persistence safeguards, and reproducible source data. Delete ceremonial smoke tests, redundant snapshots, manual hash ledgers, and duplicate CI layers.
- Keep generated reports, caches, local workspaces, downloaded datasets, and temporary development materials outside Git.
- Maintain a compact README with working installation and usage instructions; put equations, data sources, and specialist protocols in their relevant guides.
- Prefer cross-platform implementation and Linux-compatible commands. Support Windows without making PowerShell a dependency.
- Work on a branch, open a pull request, and verify the affected build and numerical workflows before merging.
