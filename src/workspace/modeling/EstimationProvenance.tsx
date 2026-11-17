import type { Dataset } from "../types";

export function EstimationProvenance({dataset}:{dataset:Dataset}) {
  const lineage = dataset.metadata.estimation;
  if (!lineage) return null;
  return <section className="ws-notice"><h3>Estimated states · processed data</h3><p>Estimates use the processed-value observation policy in downstream analyses and experiments.</p><a className="ws-link" href={`#/workspaces/${dataset.workspace_id}/estimations/${lineage.runId}`}>Reopen estimation and provenance ↗</a><details><summary>Frozen inputs, settings and provenance</summary><pre>{JSON.stringify(lineage,null,2)}</pre></details></section>;
}
