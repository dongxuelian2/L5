import { useEffect, useState } from "react";
import { downloadFile } from "../../lib/download";
import { api, message } from "../api";

type Control = { reactorTemperatureMAE: number; coolingValveTravel: number; peakReactorPressure: number; pressureSamplesAbove3000: number };
type Report = {
  diagnosis: {hypothesis: string; start: number; cutoff: number} | null;
  threshold: number; signals: string[]; protocol: string;
  signatureDistances: Record<string, number>;
  comparison: Record<string, Control>;
  detection: { normal: { alarmSamples: number; observedSamples: number }; events: { delay: number | null }[] };
};
type Study = { activeStage?: string; signals?: string[]; datasets: Record<string, string>; analysisId?: string; experimentId?: string; incidentId?: string; report?: Report };

export function IndustrialStudy({ workspaceId, onChanged }: { workspaceId: string; onChanged: () => void }) {
  const path = `/workspaces/${workspaceId}/industrial-study`;
  const [study, setStudy] = useState<Study>({ datasets: {} });
  const [status, setStatus] = useState("Opening study…");
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function restore() {
      try {
        const saved = await api<Study>(path, undefined, "GET", controller.signal);
        if (controller.signal.aborted) return;
        setStudy(saved);
        if (saved.activeStage) {
          setStatus(saved.activeStage === "measurements" ? "Preparing measurements…" : "Completing investigation…");
          timer = setTimeout(restore, 1000);
        } else setStatus("");
      } catch (e) {
        if (!controller.signal.aborted) { setError(message(e)); setStatus(""); }
      }
    }
    void restore();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [path]);
  async function run() {
    setError("");
    try {
      setStatus("Simulating independent normal and disturbed runs…");
      setStudy(await api<Study>(path, { stage: "measurements" }));
      onChanged();
      setStatus("Comparing fault signatures and the matched control intervention…");
      setStudy(await api<Study>(path, { stage: "investigation" }));
      onChanged();
    } catch (e) { setError(message(e)); }
    finally { setStatus(""); }
  }
  const report = study.report;
  const delay = report?.detection.events[0]?.delay;
  const context = new URLSearchParams((study.signals || []).map(signal => ["signal", signal]));
  if (study.incidentId && study.analysisId && study.experimentId) {
    context.set("incident", study.incidentId);
    context.set("analysis", study.analysisId);
    context.set("experiment", study.experimentId);
    context.set("dataset", study.datasets.evaluation);
  }
  if (report?.diagnosis) {
    context.set("start", String(report.diagnosis.start));
    context.set("end", String(report.diagnosis.cutoff));
  }
  return <section className="ws-panel" aria-label="Industrial process study">
    <h2>Reactor cooling-water study</h2>
    <p>Tennessee Eastman · Mode 1 · 24 hours. At hour eight the reactor cooling-water inlet warms by 5 °C.</p>
    {!report && <button className="ws-primary" disabled={!!status} onClick={() => void run()}>{study.datasets.evaluation ? "Resume study" : "Run study"}</button>}
    {status && <p role="status">{status}</p>}{error && <p role="alert">{error}</p>}
    {study.datasets.evaluation && <p><a className="ws-link" href={`#/workspaces/${workspaceId}/datasets/${study.datasets.evaluation}?${context}`}>Inspect simulated measurements ↗</a></p>}
    {report && <>
      <h3>{delay == null ? "No confirmed alarm during the event" : `Alarm confirmed ${delay / 60} min after injection`}</h3>
      <p>{report.detection.normal.alarmSamples} alarm samples among {report.detection.normal.observedSamples} labelled normal observations.</p>
      {report.diagnosis && <p><strong>Closest trajectory</strong> · {report.diagnosis.hypothesis.replace("-reference", " cooling water")}. Observed through {report.diagnosis.cutoff} s.</p>}
      <details><summary>Diagnostic evidence</summary><p>Root mean square whitened residual over the same observed ticks for each candidate. The two cooling-water models estimate onset independently within 30 minutes before the alarm.</p>
      <ul>{Object.entries(report.signatureDistances).map(([key, value]) => <li key={key}>{key.replace("-reference", " cooling water")}: {value.toFixed(2)}</li>)}</ul>
      <p>Channels: {report.signals.join(", ")}. Calibrated squared-distance threshold: {report.threshold.toFixed(2)}. Two consecutive exceedances confirm an alarm.</p></details>
      <p className="ws-inline"><a className="ws-link" href={`#/workspaces/${workspaceId}/analysis/${study.analysisId}?${context}`}>Saved detection analysis ↗</a>
      <a className="ws-link" href={`#/workspaces/${workspaceId}/experiments/${study.experimentId}?${context}`}>Open experiment ↗</a>
      <a className="ws-link" href={`#/workspaces/${workspaceId}/incidents/${study.incidentId}?${context}`}>Investigate incident ↗</a></p>
      <h3>Control intervention</h3><div className="ws-table-scroll"><table><thead><tr><th>Cooling loop</th><th>Temperature MAE (°C)</th><th>Sampled valve travel (pp)</th><th>Peak pressure (kPa gauge)</th></tr></thead><tbody>{Object.entries(report.comparison).map(([key, c]) => <tr key={key}><td>{key === "evaluation" ? "Baseline" : "Half gain after hour 8"}</td><td>{c.reactorTemperatureMAE.toFixed(4)}</td><td>{c.coolingValveTravel.toFixed(2)}</td><td>{c.peakReactorPressure.toFixed(2)}</td></tr>)}</tbody></table></div>
      <p><a className="ws-link" href={`#/workspaces/${workspaceId}/datasets/${study.datasets.intervention}?${context}`}>Inspect counterfactual trajectory ↗</a></p>
      <a className="ws-link" download href={`/api/incidents/${study.incidentId}/report.html?download=1`}>Export investigation report</a>{" · "}
      <button onClick={() => downloadFile("tep-cooling-study.json", JSON.stringify(report, null, 2))}>Export evidence JSON</button>
    </>}
  </section>;
}
