import { useEffect, useMemo, useState, type FormEvent } from "react";
import { t as tr } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { analysisPath, api, message } from "./api";
import { Plot } from "./Charts";
import type { LiveEvent, LiveRange, LiveReading, LiveSample, LiveSession, LiveWindow } from "./liveTypes";
import type { Dataset, TimeAxis } from "./types";

const displayLimit = 1000;
const datePattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/;
const utcEpoch = "1970-01-01T00:00:00Z";
function seconds(value: string) {
  const subMilliseconds = value.match(/\.\d{3}(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1];
  return Date.parse(value) / 1000 + (subMilliseconds ? Number(`0.000${subMilliseconds}`) : 0);
}

export function sampleDate(value?: string | null) {
  return value ? value.replace("T", " ").replace(/\+00:00$/, "Z") : "—";
}

export function readingValue(value: unknown) {
  if (value === undefined || value === null) return "—";
  if (typeof value === "number") return String(value);
  if (typeof value === "boolean") return tr(value ? "live.value.on" : "live.value.off");
  const text = typeof value === "string" ? value : JSON.stringify(value) ?? "—";
  return text.length > 160 ? text.slice(0, 157) + "…" : text;
}

export function LiveQuality({ sample }: { sample: LiveReading }) {
  const hexCode = `0x${sample.status_code.toString(16).padStart(8, "0")}`;
  return <span className="live-quality" data-quality={sample.quality} title={hexCode}>
    <span>{tr(`live.quality.${sample.quality}`)}</span>
    <code>{sample.status_name}</code>
  </span>;
}

function numericReading(sample: LiveSample) {
  if (sample.quality !== "good") return null;
  if (typeof sample.value === "number" && Number.isFinite(sample.value)) return sample.value;
  if (typeof sample.value === "boolean") return Number(sample.value);
  return null;
}

function groupedSamples(samples: LiveSample[]) {
  const groups = new Map<string, LiveSample[]>();
  for (const sample of samples) {
    const group = groups.get(sample.signal_id);
    if (group) group.push(sample);
    else groups.set(sample.signal_id, [sample]);
  }
  return groups;
}

function interruptionGaps(events: LiveEvent[], last: number) {
  const gaps: { start: number; end: number }[] = [];
  let interruptedAt: number | undefined;
  for (const event of events) {
    if (event.kind === "connection_interrupted") interruptedAt ??= seconds(event.timestamp);
    if (event.kind === "connection_restored" && interruptedAt !== undefined) {
      gaps.push({ start: interruptedAt, end: seconds(event.timestamp) });
      interruptedAt = undefined;
    }
  }
  if (interruptedAt !== undefined && interruptedAt <= last) gaps.push({ start: interruptedAt, end: last });
  return gaps;
}

export function LiveEvidence({ prefix, session, onDataset }: {
  prefix: string;
  session: LiveSession;
  onDataset: (dataset: Dataset) => void;
}) {
  const [view, setView] = useState<LiveWindow | null>(null);
  const [paused, setPaused] = useState(false);
  const [scope, setScope] = useState<LiveRange>({});
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number>();
  const [signals, setSignals] = useState(session.mappings.slice(0, 4).map(mapping => mapping.signal_id));
  const recording = session.state === "recording";

  useEffect(() => {
    if (recording && paused) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ limit: String(displayLimit), include_latest: "1" });
    if (!recording) {
      if (scope.start) params.set("start", scope.start);
      if (scope.end) params.set("end", scope.end);
    }
    let timer: number | undefined;
    async function load() {
      try {
        const data = await api<LiveWindow>(`${prefix}/sessions/${session.id}/samples?${params}`, undefined, "GET", controller.signal);
        if (!controller.signal.aborted) { setView(data); setError(""); }
      } catch (e) {
        if (!controller.signal.aborted) setError(message(e));
      } finally {
        if (recording && !controller.signal.aborted) timer = window.setTimeout(load, 1000);
      }
    }
    void load();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [prefix, session.id, recording, paused, scope]);

  const sorted = useMemo(() => [...(view?.samples ?? [])].sort((a, b) => a.timestamp.localeCompare(b.timestamp) || a.id - b.id), [view]);
  const events = useMemo(() => [...(view?.events ?? [])].sort((a, b) => a.timestamp.localeCompare(b.timestamp) || a.id - b.id), [view]);
  const groups = useMemo(() => groupedSamples(sorted), [sorted]);
  const latest = useMemo(() => new Map(view?.latest?.map(sample => [sample.signal_id, sample])), [view]);
  const first = sorted[0]?.timestamp;
  const last = sorted.at(-1)?.timestamp;
  const domain: [number, number] | undefined = first && last ? [seconds(first), seconds(last)] : undefined;
  const axis: TimeAxis = { kind: "datetime", origin: utcEpoch, column: null, start: domain?.[0] ?? 0, end: domain?.[1] ?? 0 };
  const gaps = domain ? interruptionGaps(events, domain[1]) : [];

  function applyScope(next: LiveRange) {
    setScope(next);
    setView(null);
    setSelected(undefined);
    setError("");
  }

  return <>
    <section className="ws-panel live-panel" aria-labelledby="live-evidence-title">
      <div className="ws-section-heading">
        <div><h2 id="live-evidence-title">{session.name}</h2><p className="live-hint"><code>{session.config.endpoint}</code></p></div>
        {recording ? <button type="button" className="ws-outlined" aria-pressed={paused} onClick={() => setPaused(value => !value)}>{tr(paused ? "Resume display" : "Pause display")}</button>
          : <span className="live-state" data-state={session.state}>{tr(`live.session.${session.state}`)}</span>}
      </div>
      <dl className="live-connection-facts">
        <div><dt>{tr("Recording started")}</dt><dd>{sampleDate(session.started_at)}</dd></div>
        <div><dt>{tr("Recording stopped")}</dt><dd>{sampleDate(session.stopped_at)}</dd></div>
      </dl>
      {recording && paused && <p className="ws-notice">{tr("Display paused. Acquisition continues.")}</p>}
      {!recording && <HistoricalInterval apply={applyScope} scope={scope} first={first} last={last} />}
      {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
      {!view && !error && <p className="live-hint" role="status">{tr("Loading recorded observations…")}</p>}
      {view && <>
        <h3>{tr("Latest values in view")}</h3>
        <div className="ws-table-scroll"><table>
          <thead><tr><th>{tr("Signal")}</th><th>{tr("Raw value")}</th><th>{tr("Quality")}</th><th>{tr("Observation timestamp")}</th><th>{tr("Source timestamp")}</th><th>{tr("Server timestamp")}</th><th>{tr("L5 signal ID")}</th></tr></thead>
          <tbody>{session.mappings.map(mapping => {
            const sample = latest.get(mapping.signal_id) ?? groups.get(mapping.signal_id)?.at(-1);
            return <tr key={mapping.signal_id}>
              <th scope="row">{mapping.display_name} <span className="ws-muted">{mapping.unit}</span><br /><code className="ws-muted">{mapping.node_id}</code></th>
              <td className={sample && sample.quality !== "good" ? "ws-muted" : ""}>{readingValue(sample?.value)}</td>
              <td>{sample ? <LiveQuality sample={sample} /> : tr("No observation")}</td>
              <td>{sampleDate(sample?.timestamp)}</td><td>{sampleDate(sample?.source_timestamp)}</td><td>{sampleDate(sample?.server_timestamp)}</td>
              <td><code>{mapping.signal_id}</code></td>
            </tr>;
          })}</tbody>
        </table></div>
        {domain ? <>
          <h3>{tr("Synchronized trends")}</h3>
          <p className="live-hint">{tr("Charts show good numeric and Boolean values. Bad or missing observations leave gaps. Times use source, then server, then receipt time.")}</p>
          <fieldset className="live-plot-picker"><legend>{tr("Signals to plot")}</legend>
            {session.mappings.map(mapping => <label key={mapping.signal_id}>
              <input type="checkbox" checked={signals.includes(mapping.signal_id)} onChange={e => {
                const checked = e.currentTarget.checked;
                setSignals(current => checked ? [...current, mapping.signal_id] : current.filter(id => id !== mapping.signal_id));
              }} />
              {mapping.display_name}
            </label>)}
          </fieldset>
          <div className="ws-signal-plots">{session.mappings.filter(mapping => signals.includes(mapping.signal_id)).map(mapping => {
            const samples = groups.get(mapping.signal_id);
            const title = mapping.unit ? `${mapping.display_name} (${mapping.unit})` : mapping.display_name;
            return samples?.length
              ? <Plot key={mapping.signal_id} title={title} axis={axis} times={samples.map(sample => seconds(sample.timestamp))} values={samples.map(numericReading)} timeDomain={domain} gaps={gaps} selectedTime={selected} onSelectTime={setSelected} showIsolatedPoints />
              : <p key={mapping.signal_id} className="ws-notice">{tr("{0} has no observations in this window.", {0: title})}</p>;
          })}</div>
          {sorted.length >= displayLimit && <p className="live-hint">{tr("Showing the newest {0} observations in the selected window.", {0: displayLimit.toLocaleString()})}</p>}
        </> : <p className="ws-notice">{tr(recording ? "Waiting for OPC UA observations." : "This interval contains no observations.")}</p>}
        <details>
          <summary>{tr("Recent raw observations")}</summary>
          <div className="ws-table-scroll"><table>
            <thead><tr><th>{tr("NodeId")}</th><th>{tr("Raw value")}</th><th>{tr("Quality")}</th><th>{tr("Observation timestamp")}</th><th>{tr("Timestamp origin")}</th><th>{tr("Source timestamp")}</th><th>{tr("Server timestamp")}</th><th>{tr("Receipt timestamp")}</th></tr></thead>
            <tbody>{sorted.slice(-24).reverse().map(sample => <tr key={sample.id}>
              <td><code>{sample.node_id}</code></td><td>{readingValue(sample.value)}</td><td><LiveQuality sample={sample} /></td>
              <td>{sampleDate(sample.timestamp)}</td><td>{tr(`live.timestamp.${sample.timestamp_origin}`)}</td>
              <td>{sampleDate(sample.source_timestamp)}</td><td>{sampleDate(sample.server_timestamp)}</td><td>{sampleDate(sample.received_at)}</td>
            </tr>)}</tbody>
          </table></div>
        </details>
      </>}
    </section>
    {view && <EventLog events={events} />}
    {!recording && <DatasetExport prefix={prefix} session={session} scope={scope} onDataset={onDataset} />}
  </>;
}

function HistoricalInterval({ apply, scope, first, last }: {
  apply: (range: LiveRange) => void;
  scope: LiveRange;
  first?: string;
  last?: string;
}) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [error, setError] = useState("");
  function update(nextStart: string, nextEnd: string) {
    const start = nextStart.trim(), end = nextEnd.trim();
    if ([start, end].some(date => date && (!datePattern.test(date) || !Number.isFinite(seconds(date)))) ||
      (start && end && seconds(start) > seconds(end))) {
      setError(tr("Enter ISO timestamps with a timezone and a start at or before the end."));
      return;
    }
    setError("");
    setStart(start);
    setEnd(end);
    apply({ start: start || undefined, end: end || undefined });
  }
  return <form className="live-history" onSubmit={e => { e.preventDefault(); update(start, end); }}>
    <h3>{tr("Historical interval")}</h3>
    <p className="live-hint">{tr("Enter ISO timestamps with a timezone. Leave both blank for the whole recording.")}</p>
    <div className="ws-form-grid">
      <label>{tr("Interval start")}<input placeholder="2026-01-01T08:00:00Z" value={start} onChange={e => setStart(e.target.value)} /></label>
      <label>{tr("Interval end")}<input placeholder="2026-01-01T08:15:00Z" value={end} onChange={e => setEnd(e.target.value)} /></label>
    </div>
    <div className="ws-inline live-actions">
      <button className="ws-outlined">{tr("Apply interval")}</button>
      <button className="ws-outlined" type="button" onClick={() => { if (first && last) update(first, last); }} disabled={!first || !last}>{tr("Use displayed time range")}</button>
      <button className="ws-outlined" type="button" onClick={() => update("", "")} disabled={!scope.start && !scope.end && !start && !end}>{tr("Whole recording")}</button>
    </div>
    {error && <p className="ws-error" role="alert">{error}</p>}
  </form>;
}

function EventLog({ events }: { events: LiveEvent[] }) {
  const limit = 60;
  return <section className="ws-panel live-panel" aria-labelledby="live-events-title">
    <div className="ws-section-heading"><h2 id="live-events-title">{tr("Interruptions and data quality events")}</h2></div>
    {events.length ? <div className="ws-table-scroll live-event-log"><table>
      <thead><tr><th>{tr("Event time (UTC)")}</th><th>{tr("Event")}</th><th>{tr("NodeId")}</th><th>{tr("Count")}</th><th>{tr("Details")}</th></tr></thead>
      <tbody>{events.slice(-limit).reverse().map(event => {
        const key = `live.event.${event.kind}`;
        const label = tr(key);
        return <tr key={event.id}><td>{sampleDate(event.timestamp)}</td>
          <th scope="row">{label === key ? event.kind : label}</th>
          <td><code>{event.node_id || "—"}</code></td>
          <td>{event.count ?? "—"}</td>
          <td className="live-event-detail">{errorMessage(event.detail)}</td></tr>;
      })}</tbody>
    </table></div> : <p className="live-hint">{tr("No interruptions or loss events in this window.")}</p>}
    {events.length > limit && <p className="live-hint">{tr("Showing the newest {0} events in the selected window.", {0: limit.toLocaleString()})}</p>}
  </section>;
}

function DatasetExport({ prefix, session, scope, onDataset }: {
  prefix: string;
  session: LiveSession;
  scope: LiveRange;
  onDataset: (dataset: Dataset) => void;
}) {
  const [name, setName] = useState(session.name);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Dataset | null>(null);
  const [error, setError] = useState("");
  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    setSaved(null);
    try {
      const dataset = await api<Dataset>(`${prefix}/sessions/${session.id}/dataset`, { name: name.trim(), ...scope });
      setSaved(dataset);
      onDataset(dataset);
    } catch (e) {
      setError(message(e));
    } finally {
      setSaving(false);
    }
  }
  return <form className="ws-panel live-panel" onSubmit={e => void save(e)} aria-labelledby="live-export-title">
    <div className="ws-section-heading"><h2 id="live-export-title">{tr("Create an L5 dataset")}</h2></div>
    <p className="live-hint">{scope.start || scope.end
      ? tr("Export interval {0} → {1}", {0: scope.start || tr("Recording start"), 1: scope.end || tr("Recording end")})
      : tr("Export the whole recording.")}</p>
    <p className="live-hint">{tr("The dataset keeps good numeric and Boolean values. Raw OPC UA values, timestamps and quality remain in this recording.")}</p>
    <div className="live-record-form">
      <label>{tr("Dataset name")}<input value={name} onChange={e => setName(e.target.value)} maxLength={160} required /></label>
      <button className="ws-primary" disabled={saving || !name.trim()}>{tr(saving ? "Saving dataset…" : "Create dataset")}</button>
    </div>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {saved && <div className="ws-inline live-actions" role="status">
      <a className="ws-link" href={`#/workspaces/${session.workspace_id}/datasets/${saved.id}`}>{tr("Open dataset ↗")}</a>
      <a className="ws-link" href={`#/${analysisPath(session.workspace_id, saved.id, saved.metadata.columns.map(column => column.name))}`}>{tr("Configure analysis ↗")}</a>
    </div>}
  </form>;
}
