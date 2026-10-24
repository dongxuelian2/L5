import { useEffect, useRef, useState } from "react";
import { message } from "./api";
import type { Incident } from "./types";

export function IncidentReport({ incident }: { incident: Incident }) {
  const [html, setHtml] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false), [ready, setReady] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null), generation = useRef(0);
  useEffect(() => { generation.current++; setHtml(""); setReady(false); setBusy(false); }, [incident]);
  async function generate() {
    const request = ++generation.current;
    setBusy(true); setError(""); setReady(false);
    try {
      const response = await fetch(`/api/incidents/${incident.id}/report.html`);
      if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) throw new Error("无法生成报告，请检查本地服务。");
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
  return <section className="ws-panel incident-report" id="incident-report" aria-label="专业调查报告">
    <div className="ws-section-heading"><div><h2>专业调查报告</h2><p className="ws-muted">从最新保存的事件、测量、分析和实验生成。请先保存正在编辑的内容。</p></div><button className="ws-primary" disabled={busy} onClick={() => void generate()}>{busy ? "正在生成报告…" : html ? "重新生成报告" : "生成报告"}</button></div>
    {error && <p role="alert" className="ws-error">{error}</p>}
    <div className="ws-inline incident-actions">
      <button disabled={!html || busy} onClick={() => download(html, "html", "text/html;charset=utf-8")}>导出离线 HTML</button>
      <button disabled={!html || !ready || busy} onClick={() => { frame.current?.contentWindow?.focus(); frame.current?.contentWindow?.print(); }}>打印 / 保存 PDF</button>
      <button onClick={() => download(JSON.stringify(incident, null, 2), "json", "application/json")}>导出事件 JSON</button>
      {html && <a className="ws-link" href={`/api/incidents/${incident.id}/report.html`} target="_blank" rel="noreferrer">独立打开报告 ↗</a>}
    </div>
    <p className="ws-muted">HTML 内含全部图表，可离线独立打开。PDF 通过浏览器打印保存，使用报告的 A4 分页样式；打印前等待预览完成。</p>
    {html ? <iframe ref={frame} title="专业调查报告预览" srcDoc={html} onLoad={() => setReady(true)} /> : <p className="ws-notice">生成后可预览封面摘要、事件演变、检测比较、真实曲线、调查证据、模拟方案和技术附录。</p>}
  </section>;
}
