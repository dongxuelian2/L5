import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
import { useEffect, useRef, useState } from "react";
import { message } from "./api";
import type { Experiment } from "./experimentTypes";

export function ExperimentReport({ experiment, dirty }: { experiment: Experiment; dirty: boolean }) {
  const locale = useLocale();
  const [html, setHtml] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false), [runId, setRunId] = useState("");
  const [ready, setReady] = useState(false), frame = useRef<HTMLIFrameElement>(null), generation = useRef(0);
  useEffect(() => { generation.current++; setHtml(""); setReady(false); setBusy(false); }, [experiment.id, experiment.revision, runId, locale]);
  useEffect(() => () => { generation.current++; }, []);
  const url = `/api/experiments/${experiment.id}/report.html?lang=${locale}${runId ? `&run=${runId}` : ""}`;
  async function generate() {
    const request = ++generation.current; setBusy(true); setError(""); setReady(false);
    try {
      const response = await fetch(url);
      if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) throw new Error("Unable to generate experiment report from the local service.");
      const content = await response.text(); if (request === generation.current) setHtml(content);
    } catch (e) { if (request === generation.current) setError(message(e)); }
    finally { if (request === generation.current) setBusy(false); }
  }
  return <section id="experiment-report" className="ws-panel experiment-report" aria-label={tr("Experiment research report")}><div className="ws-section-heading"><div><h2>{tr("Experiment report")}</h2><p className="ws-muted">{tr("Configuration, provenance, actual detection curves, evaluation and saved research notes.")}</p></div><button type="button" className="ws-primary" disabled={busy || dirty} onClick={() => void generate()}>{busy ? tr("Generating report…") : html ? tr("Regenerate report") : tr("Preview experiment report")}</button></div>
    <label>{tr("Report executions")}<select value={runId} onChange={e => setRunId(e.target.value)}><option value="">{tr("All saved runs")}</option>{experiment.runs.map(run => <option key={run.id} value={run.id}>{run.created_at} · {tr(run.status)} · {run.id.slice(0,8)}</option>)}</select></label>
    {dirty && <p className="ws-notice">{tr("Save the edited notes and definition before generating the report.")}</p>}
    {error && <p role="alert" className="ws-error">{errorMessage(error)}</p>}
    {html && <><div className="ws-inline"><a className="ws-link" href={`${url}&download=1`} download>{tr("Export offline HTML ↗")}</a><a className="ws-link" href={url} target="_blank" rel="noreferrer">{tr("Open saved report ↗")}</a><button type="button" disabled={!ready || busy} onClick={() => { frame.current?.contentWindow?.focus(); frame.current?.contentWindow?.print(); }}>{tr("Print / Save A4 PDF")}</button></div><iframe ref={frame} title={tr("Experiment report preview")} srcDoc={html} onLoad={() => setReady(true)} /></>}
  </section>;
}
