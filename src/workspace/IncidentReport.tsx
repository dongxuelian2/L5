import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
import { downloadFile } from "../lib/download";
import { useReportPreview } from "./useReportPreview";
import type { Incident } from "./types";

export function IncidentReport({ incident }: { incident: Incident }) {
  const locale = useLocale();
  const url = `/api/incidents/${incident.id}/report.html?lang=${locale}`;
  const { html, error, busy, ready, frame, setReady, generate, print } = useReportPreview(url, incident, "无法生成报告，请检查本地服务。");
  return <section className="ws-panel incident-report" id="incident-report" aria-label={tr("专业调查报告")}>
    <div className="ws-section-heading"><div><h2>{tr("专业调查报告")}</h2><p className="ws-muted">{tr("从最新保存的事件、测量、分析和实验生成。请先保存正在编辑的内容。")}</p></div><button className="ws-primary" disabled={busy} onClick={() => void generate()}>{busy ? tr("正在生成报告…") : html ? tr("重新生成报告") : tr("生成报告")}</button></div>
    {error && <p role="alert" className="ws-error">{errorMessage(error)}</p>}
    <div className="ws-inline incident-actions">
      <button disabled={!html || busy} onClick={() => downloadFile(`l5-incident-${incident.id}.html`, html, "text/html;charset=utf-8")}>{tr("导出离线 HTML")}</button>
      <button disabled={!html || !ready || busy} onClick={print}>{tr("打印 / 保存 PDF")}</button>
      <button onClick={() => downloadFile(`l5-incident-${incident.id}.json`, JSON.stringify(incident, null, 2))}>{tr("导出事件 JSON")}</button>
      {html && <a className="ws-link" href={url} target="_blank" rel="noreferrer">{tr("独立打开报告 ↗")}</a>}
    </div>
    <p className="ws-muted">{tr("HTML 内含全部图表，可离线独立打开。PDF 通过浏览器打印保存，使用报告的 A4 分页样式；打印前等待预览完成。")}</p>
    {html ? <iframe ref={frame} title={tr("专业调查报告预览")} srcDoc={html} onLoad={() => setReady(true)} /> : <p className="ws-notice">{tr("生成后可预览封面摘要、事件演变、检测比较、真实曲线、调查证据、模拟方案和技术附录。")}</p>}
  </section>;
}
