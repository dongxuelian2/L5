import { useEffect, useRef, useState, type FormEvent } from "react";
import { errorMessage } from "../../lib/text";
import { api, go, message } from "../api";
import { SensorPlacementForm } from "./SensorPlacementForm";
import { SensorPlacementResults } from "./SensorPlacementResults";
import type { Options, Run, SavedRun, Setup, TrajectoryRequest } from "./sensorPlacementTypes";
import type { Dataset } from "../types";
import "./sensorPlacement.css";

export function SensorPlacementWorkspace({ workspaceId, runId, onChanged }: {
  workspaceId: string; runId?: string; onChanged: () => void;
}) {
  const endpoint = "/workspaces/" + workspaceId + "/sensor-placement";
  const [options, setOptions] = useState<Options>();
  const [saved, setSaved] = useState<SavedRun[]>([]);
  const [run, setRun] = useState<Run>();
  const [config, setConfig] = useState<Setup>();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);

  useEffect(() => {
    const request = new AbortController();
    setLoading(true);
    setBusy(false);
    setError("");
    Promise.all([api<Options>(endpoint, undefined, "GET", request.signal),
      runId ? api<Run>(endpoint + "/" + runId, undefined, "GET", request.signal) : Promise.resolve(undefined)])
      .then(([data, current]) => {
        if (request.signal.aborted) return;
        setOptions(data);
        setSaved(data.runs);
        setRun(current);
        setConfig(current?.analysis.config ?? data.defaults);
        setName(current?.name ?? "");
      }).catch(e => { if (!request.signal.aborted) setError(message(e)); })
      .finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => { request.abort(); pending.current?.abort(); };
  }, [endpoint, runId]);

  async function execute(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError("");
    try {
      const current = await api<Run>(endpoint, { name, config }, "POST", controller.signal);
      if (!controller.signal.aborted) go(endpoint.slice(1) + "/" + current.id);
    } catch (e) {
      if (!controller.signal.aborted) setError(message(e));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  async function publish(request: TrajectoryRequest) {
    if (!run || busy) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError("");
    try {
      const dataset = await api<Dataset>(endpoint + "/" + run.id + "/dataset", request, "POST", controller.signal);
      if (!controller.signal.aborted) {
        onChanged();
        go("workspaces/" + workspaceId + "/explorer/" + dataset.metadata.columns.map(column => column.id).join(","));
      }
    } catch (e) {
      if (!controller.signal.aborted) setError(message(e));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <div className="sensor-workspace">
    <header className="ws-page-title"><div>
      <h1>Fault detectability and sensor placement</h1>
      <p>Compare fault trajectories under declared noise and choose measurements within an installation budget.</p>
    </div></header>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {loading ? <p role="status">Loading</p> : options && config && <>
      <div className="ws-panel sensor-actions">
        <label>Saved sensor studies<select value={runId ?? ""} disabled={busy} onChange={e =>
          go(endpoint.slice(1) + (e.target.value ? "/" + e.target.value : ""))}>
          <option value="">New sensor study</option>
          {saved.map(item => <option key={item.id} value={item.id}>{item.name} · {new Date(item.created_at).toLocaleString("en")}</option>)}
        </select></label>
        {run && <>
          <a className="ws-outlined" href={"/api" + endpoint + "/" + run.id + "/analysis.json"}>Download analysis JSON</a>
          <a className="ws-outlined" href={"/api" + endpoint + "/" + run.id + "/report.html?download=1"}>Download offline report</a>
          <a className="ws-outlined" href={"/api" + endpoint + "/" + run.id + "/report.html"}
            target="_blank" rel="noreferrer">Open offline report</a>
        </>}
      </div>
      {run ? <details className="sensor-edit"><summary>Edit settings and save a new run</summary>
        <SensorPlacementForm {...{ options, config, setConfig, name, setName, busy }} onRun={execute} />
      </details> : <SensorPlacementForm {...{ options, config, setConfig, name, setName, busy }} onRun={execute} />}
      {busy && <p role="status">Processing sensor study…</p>}
      {run && <SensorPlacementResults key={run.id} analysis={run.analysis} publish={publish} busy={busy} />}
    </>}
  </div>;
}
