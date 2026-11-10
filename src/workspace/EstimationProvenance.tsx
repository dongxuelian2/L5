import { t as tr, useLocale } from "../i18n";
import type { Dataset } from "./types";

export function EstimationProvenance({dataset}:{dataset:Dataset}) {
  useLocale();
  const lineage = dataset.metadata.estimation;
  if (!lineage) return null;
  return <section className="ws-notice"><h3>{tr("Estimated states · processed data")}</h3><p>{tr("Estimates use the processed-value observation policy in downstream analyses and experiments.")}</p><a className="ws-link" href={`#/workspaces/${dataset.workspace_id}/estimations/${lineage.runId}`}>{tr("Reopen estimation and provenance")} ↗</a><details><summary>{tr("Frozen inputs, settings and provenance")}</summary><pre>{JSON.stringify(lineage,null,2)}</pre></details></section>;
}
