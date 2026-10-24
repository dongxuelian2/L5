import { useEffect, useRef, useState } from "react";
import { message } from "./api";
import type { Experiment } from "./experimentTypes";

export function ExperimentReport({ experiment, dirty }: { experiment: Experiment; dirty: boolean }) {
  const [html, setHtml] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false), [runId, setRunId] = useState("");
  const [ready, setReady] = useState(false), frame = useRef<HTMLIFrameElement>(null), generation = useRef(0);
  useEffect(() => { generation.current++; setHtml(""); setReady(false); setBusy(false); }, [experiment.id, experiment.revision, runId]);
  useEffect(() => () => { generation.current++; }, []);
  const url = `/api/experiments/${experiment.id}/report.html${runId ? `?run=${runId}` : ""}`;
  async function generate() {
    const request = ++generation.current; setBusy(true); setError(""); setReady(false);
    try {
      const response = await fetch(url);
      if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) throw new Error("Unable to generate experiment report from the local service.");
      const content = await response.text(); if (request === generation.current) setHtml(content);
    } catch (e) { if (request === generation.current) setError(message(e)); }
    finally { if (request === generation.current) setBusy(false); }
  }
  return <section id="experiment-report" className="ws-panel experiment-report" aria-label="Experiment research report"><div className="ws-section-heading"><div><h2>Experiment report</h2><p className="ws-muted">Configuration, provenance, actual detection curves, evaluation and saved research notes.</p></div><button type="button" className="ws-primary" disabled={busy || dirty} onClick={() => void generate()}>{busy ? "Generating report…" : html ? "Regenerate report" : "Preview experiment report"}</button></div>
    <label>Report executions<select value={runId} onChange={e => setRunId(e.target.value)}><option value="">All saved runs</option>{experiment.runs.map(run => <option key={run.id} value={run.id}>{run.created_at} · {run.status} · {run.id.slice(0,8)}</option>)}</select></label>
    {dirty && <p className="ws-notice">Save the edited notes and definition before generating the report.</p>}
    {error && <p role="alert" className="ws-error">{error}</p>}
    {html && <><div className="ws-inline"><a className="ws-link" href={`${url}${runId ? "&" : "?"}download=1`} download>Export offline HTML ↗</a><a className="ws-link" href={url} target="_blank" rel="noreferrer">Open saved report ↗</a><button type="button" disabled={!ready || busy} onClick={() => { frame.current?.contentWindow?.focus(); frame.current?.contentWindow?.print(); }}>Print / Save A4 PDF</button></div><iframe ref={frame} title="Experiment report preview" srcDoc={html} onLoad={() => setReady(true)} /></>}
  </section>;
}
