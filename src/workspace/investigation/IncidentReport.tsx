import { errorMessage } from "../../lib/text";
import { useEffect, useRef, useState } from "react";
import { message } from "../api";
import type { Incident } from "../types";

export function IncidentReport({ incident }: { incident: Incident }) {
  const [html, setHtml] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false), [ready, setReady] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null), generation = useRef(0);
  useEffect(() => { generation.current++; setHtml(""); setReady(false); setBusy(false); }, [incident]);
  useEffect(() => () => { generation.current++; }, []);
  const url = `/api/incidents/${incident.id}/report.html`;
  async function generate() {
    const request = ++generation.current;
    setBusy(true); setError(""); setReady(false);
    try {
      const response = await fetch(url);
      if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) throw new Error("Unable to generate the report. Check the local service.");
      const content = await response.text();
      if (request === generation.current) setHtml(content);
    } catch (e) { if (request === generation.current) setError(message(e)); }
    finally { if (request === generation.current) setBusy(false); }
  }
  function download(content: string, extension: string, mime: string) {
    const url = URL.createObjectURL(new Blob([content], { type: mime })), a = document.createElement("a");
    a.href = url; a.download = `l5-incident-${incident.id}.${extension}`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="ws-panel incident-report" id="incident-report" aria-label="Professional investigation report">
    <div className="ws-section-heading"><div><h2>Professional investigation report</h2><p className="ws-muted">Save your edits before generating the report.</p></div><button className="ws-primary" disabled={busy} onClick={() => void generate()}>{busy ? "Generating report…" : html ? "Regenerate report" : "Generate report"}</button></div>
    {error && <p role="alert" className="ws-error">{errorMessage(error)}</p>}
    <div className="ws-inline incident-actions">
      <button disabled={!html || busy} onClick={() => download(html, "html", "text/html;charset=utf-8")}>Export offline HTML</button>
      <button disabled={!html || !ready || busy} onClick={() => { frame.current?.contentWindow?.focus(); frame.current?.contentWindow?.print(); }}>Print / Save PDF</button>
      <button onClick={() => download(JSON.stringify(incident, null, 2), "json", "application/json")}>Export incident JSON</button>
      {html && <a className="ws-link" href={url} target="_blank" rel="noreferrer">Open report separately ↗</a>}
    </div>
    {html && <iframe ref={frame} title="Professional investigation report preview" srcDoc={html} onLoad={() => setReady(true)} />}
  </section>;
}
