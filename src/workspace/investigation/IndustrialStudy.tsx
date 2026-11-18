import { useEffect, useState } from "react";
import { downloadFile } from "../../lib/download";
import { analysisPath, api, message } from "../api";

type Control = { reactorTemperatureMAE: number; coolingValveTravel: number; peakReactorPressure: number; pressureSamplesAbove3000: number };
type Report = {
  threshold: number; signals: string[]; protocol: string;
  signatureDistances: Record<string, number>;
  comparison: Record<string, Control>;
  detection: { normal: { alarmSamples: number; observedSamples: number }; events: { delay: number | null }[] };
};
type Study = { datasets: Record<string, string>; report?: Report };

export function IndustrialStudy({ workspaceId, onChanged }: { workspaceId: string; onChanged: () => void }) {
  const path = `/workspaces/${workspaceId}/industrial-study`;
  const [study, setStudy] = useState<Study>({ datasets: {} });
  const [status, setStatus] = useState("Opening study…");
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<Study>(path, undefined, "GET", controller.signal).then(setStudy)
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setStatus(""); });
    return () => controller.abort();
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
  return <section className="ws-panel" aria-label="Industrial process study">
    <h2>Reactor cooling-water study</h2>
    <p>Tennessee Eastman · Mode 1 · 24 hours. At hour eight the reactor cooling-water inlet warms by 5 °C.</p>
    {!report && <button className="ws-primary" disabled={!!status} onClick={() => void run()}>Run study</button>}
    {status && <p role="status">{status}</p>}{error && <p role="alert">{error}</p>}
    {study.datasets.evaluation && <p><a className="ws-link" href={`#/workspaces/${workspaceId}/datasets/${study.datasets.evaluation}`}>Inspect simulated measurements ↗</a></p>}
    {report && <>
      <h3>{delay == null ? "No confirmed alarm during the event" : `Alarm confirmed ${delay / 60} min after injection`}</h3>
      <p>{report.detection.normal.alarmSamples} alarm samples among {report.detection.normal.observedSamples} labelled normal observations.</p>
      <details><summary>Diagnostic evidence</summary><p>Distance from the observed one-hour alarm response to each simulated cooling-water signature, in normal covariance units. Smaller values indicate a closer match.</p>
      <ul>{Object.entries(report.signatureDistances).map(([key, value]) => <li key={key}>{key.replace("-reference", " cooling water")}: {value.toFixed(2)}</li>)}</ul>
      <p>Channels: {report.signals.join(", ")}. Calibrated squared-distance threshold: {report.threshold.toFixed(2)}. Two consecutive exceedances confirm an alarm.</p></details>
      <p><a className="ws-link" href={`#/${analysisPath(workspaceId, study.datasets.evaluation, report.signals)}`}>Analyze these five signals ↗</a></p>
      <h3>Control intervention</h3><div className="ws-table-scroll"><table><thead><tr><th>Cooling loop</th><th>Temperature MAE (°C)</th><th>Sampled valve travel (pp)</th><th>Peak pressure (kPa gauge)</th></tr></thead><tbody>{Object.entries(report.comparison).map(([key, c]) => <tr key={key}><td>{key === "evaluation" ? "Baseline" : "Half gain after hour 8"}</td><td>{c.reactorTemperatureMAE.toFixed(4)}</td><td>{c.coolingValveTravel.toFixed(2)}</td><td>{c.peakReactorPressure.toFixed(2)}</td></tr>)}</tbody></table></div>
      <p><a className="ws-link" href={`#/workspaces/${workspaceId}/datasets/${study.datasets.intervention}`}>Inspect counterfactual trajectory ↗</a></p>
      <button onClick={() => downloadFile("tep-cooling-study.json", JSON.stringify(report, null, 2))}>Export study report</button>
    </>}
  </section>;
}
