# L5 repository instructions

These rules apply to all contributions and to every directory in the repository.

1. Use English throughout the repository and application, including UI text, reports, logs, examples, comments, and project metadata. Preserve text supplied by users and original source data.
2. Write direct, affirmative, concise engineering prose. State capabilities, assumptions, and operating constraints in concrete terms.
3. Remove defensive, apologetic, self-justifying, repetitive, and contrastive prose.
4. Describe implemented functionality. Support technical claims with reproducible methods and measured results.
5. Keep the architecture and dependency set small. Prefer standard libraries, native platform features, and existing shared code.
6. Keep generated outputs, temporary files, superseded development notes, and duplicate artifacts out of the tracked tree.
7. Organize the repository around the tasks users need to perform. Keep the README as the main entry point and place essential details in linked documentation.
8. Provide Linux-compatible and cross-platform commands for installation, execution, and builds. Use portable tooling and document platform differences where they affect users.
9. Avoid PowerShell-only workflows.
10. Keep documentation, verification, and automation proportionate to the user-facing work they support.
11. Track new files only when they contribute to functionality, distribution, installation, or necessary documentation.

12. Design for human efficiency across the full workflow. Preserve context, derive meaningful defaults, and make the next useful action apparent. Measure required interactions, repeated selections, navigation, and configuration for a complete user task.

## Structure and delivery

- Keep modules flat by default. Group closely related files one level deep by capability and keep adapters thin.
- Name files and directories for their durable responsibilities. Use Git to record revisions, phases, and dates.
- Give each topic one authoritative home. Lead with the result or action the reader needs, and place detailed methods and assumptions in the relevant guide.
- Keep reproducible source and required runtime data in Git. Write generated reports, benchmark runs, and local working state to ignored directories. Use issues and pull requests for project discussion.
- Push changes to a working branch and submit them through a pull request. Update the default branch through reviewed pull request merges after required checks pass.
- Verify the affected workflows locally and expand the checks when a change crosses shared boundaries. Add CI for recurring integration needs or explicit requests.
