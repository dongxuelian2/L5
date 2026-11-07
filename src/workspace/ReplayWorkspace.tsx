import { useEffect, useRef, useState, type FormEvent } from "react";
import { t as tr, useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { downloadFile } from "../lib/download";
import { api, message } from "./api";
import { Plot } from "./Charts";
import { namedSignal, number, signalLabel, timeLabel, type Dataset, type Incident, type Interval } from "./types";
import "./replay.css";

const detectors = { "robust-maxz": "Robust Max-Z", "pca-q": "PCA-Q", ewma: "EWMA", cusum: "Page CUSUM" };
const parameters = {
  "pca-q": { key: "variance", label: "PCA variance target", initial: .9, min: .5, max: .9999 },
  ewma: { key: "smoothing", label: "EWMA smoothing", initial: .25, min: .0001, max: 1 },
  cusum: { key: "reference", label: "CUSUM reference drift", initial: .5, min: .0001, max: undefined },
} as const;
const speedOptions = [.25, .5, 1, 2, 5, 10, 25, 100];
type Detector = keyof typeof detectors;
type Decision = "normal" | "alarm" | "abstain";
type Session = {
  id: string; config: { datasetId: string; signals: string[]; algorithm: Detector }; threshold: number;
  fitSamples: number; calibrationSamples: number; sampleCount: number; start: number; end: number; alarmPageSize: number;
};
type ObservationSeries = {
  first: number; times: number[]; scores: (number | null)[]; states: Decision[];
  values: Record<string, (number | null)[]>; scoreSegments: number[]; signalSegments: Record<string, number[]>;
};
type Alarm = Interval & {
  id: number; peakIndex: number; status: "active" | "recovered" | "interrupted";
  durationSeconds: number; transitionTime: number | null;
};
type Frame = { through: number; nextTime: number | null; alarmCount: number; alarms: Alarm[]; series: ObservationSeries };
type Evidence = { alarm: Alarm; series: ObservationSeries };
type AlarmBand = Pick<Interval, "start" | "end">;
const decisions = { normal: "Normal", alarm: "Alarm active", abstain: "Insufficient measurements" };
const alarmStatuses = { active: "Active", recovered: "Recovered", interrupted: "Interrupted" };
const reading = (value: number | null | undefined) => value == null ? "—" : number(value);

export function ReplayWorkspace({ workspaceId, datasets, initialDatasetId }: {
  workspaceId: string; datasets: Dataset[]; initialDatasetId?: string;
}) {
  useLocale();
  const available = datasets.filter(dataset => !dataset.metadata.transformation);
  const [source, setSource] = useState(initialDatasetId || "");
  const [session, setSession] = useState<Session | null>(null);
  const dataset = available.find(item => item.id === source) || available[0];
  const path = `/workspaces/${workspaceId}/replays`;
  return <>
    <header className="ws-page-title"><div>
      <div className="ws-kicker">{tr("12 / PROCESS MONITORING")}</div>
      <h1>{tr("Process Replay & Monitoring")}<span className="ws-accent">.</span></h1>
      <p>{tr("Replay process observations on their original clock, monitor deviations and investigate alarms as they appear.")}</p>
    </div>{session && <button type="button" onClick={() => setSession(null)}>{tr("Configure new replay")}</button>}</header>
    {!dataset ? <section className="ws-panel">
      <h2>{tr("Add a replay source")}</h2>
      <p>{tr("Import an original dataset or save a process simulation as a Dataset to begin.")}</p>
      <div className="ws-inline">
        <a className="ws-link" href={`#/workspaces/${workspaceId}/datasets`}>{tr("Datasets")}</a>
        <a className="ws-link" href={`#/workspaces/${workspaceId}/models`}>{tr("Models")}</a>
      </div>
    </section> : session ? <ReplayDashboard key={session.id} dataset={dataset} session={session} path={`${path}/${session.id}`} workspaceId={workspaceId} /> : <>
      <label className="ws-panel replay-source">{tr("Replay dataset")}
        <select value={dataset.id} onChange={event => setSource(event.target.value)}>
          {available.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <ReplaySetup key={dataset.id} dataset={dataset} path={path} onReady={ready => { setSource(ready.config.datasetId); setSession(ready); }} />
    </>}
  </>;
}

function ReplaySetup({ dataset, path, onReady }: { dataset: Dataset; path: string; onReady: (session: Session) => void }) {
  const { time, columns, suggestedRanges } = dataset.metadata;
  const [signals, setSignals] = useState(columns.slice(0, 3).map(column => column.name));
  const [algorithm, setAlgorithm] = useState<Detector>("robust-maxz");
  const [parameterValue, setParameterValue] = useState<number>();
  const [alpha, setAlpha] = useState(.01);
  const [persistence, setPersistence] = useState(3);
  const [baseline, setBaseline] = useState<number[]>(suggestedRanges?.baselineRange || [time.start, time.start]);
  const [replay, setReplay] = useState<number[]>([suggestedRanges?.analysisRange[0] ?? time.start, time.end]);
  const [confirmed, setConfirmed] = useState(false);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  const parameter = algorithm === "robust-maxz" ? undefined : parameters[algorithm];
  async function prepare(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    const controller = new AbortController();
    request.current = controller;
    try {
      const result = await api<Session>(path, {
        datasetId: dataset.id, signals, algorithm, alpha, persistence, baselineRange: baseline, analysisRange: replay,
        ...(parameter ? { [parameter.key]: parameterValue ?? parameter.initial } : {}),
      }, "POST", controller.signal);
      if (!controller.signal.aborted) onReady(result);
    } catch (failure) {
      if (!controller.signal.aborted) setError(message(failure));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return <form className="ws-panel replay-setup" onSubmit={prepare}>
    <h2>{tr("Configure monitoring")}</h2>
    <p className="ws-muted">{tr("Choose a known normal period before replay. L5 fits on its first 70% and calibrates on the rest, with at least 30 observations in each partition.")}</p>
    <div className="replay-range-note">{timeLabel(time, time.start)} → {timeLabel(time, time.end)} · {tr("Enter window boundaries in dataset seconds.")}</div>
    <div className="ws-form-grid">
      {([
        ["Normal training start", baseline, setBaseline, 0], ["Normal training end", baseline, setBaseline, 1],
        ["Replay start", replay, setReplay, 0], ["Replay end", replay, setReplay, 1],
      ] as const).map(([label, range, update, index]) => <label key={label}>{tr(label)}
        <input required type="number" step="any" min={time.start} max={time.end} value={Number.isNaN(range[index]) ? "" : range[index]}
          onChange={event => {
            const value = event.target.valueAsNumber;
            update(range.map((old, i) => i === index ? value : old));
            if (update === setBaseline) setConfirmed(false);
          }} />
      </label>)}
    </div>
    <fieldset className="ws-signal-picker">
      <legend>{tr("Monitored signals")} <span className="ws-muted">{signals.length} / 12</span></legend>
      <input aria-label={tr("Filter signals…")} placeholder={tr("Filter signals…")} value={filter} onChange={event => setFilter(event.target.value)} />
      <div className="ws-signal-list">{columns.filter(column => signalLabel(column).toLowerCase().includes(filter.toLowerCase())).map(column => {
        const checked = signals.includes(column.name);
        return <label key={column.name}><input type="checkbox" checked={checked} disabled={!checked && signals.length >= 12}
          onChange={() => { setSignals(checked ? signals.filter(name => name !== column.name) : [...signals, column.name]); setConfirmed(false); }} />
          <span>{signalLabel(column)}</span></label>;
      })}</div>
    </fieldset>
    <div className="ws-form-grid">
      <label>{tr("Detector")}<select value={algorithm} onChange={event => { setAlgorithm(event.target.value as Detector); setParameterValue(undefined); }}>
        {Object.entries(detectors).map(([id, label]) => <option key={id} value={id}>{tr(label)}</option>)}
      </select></label>
      <label>{tr("Calibration alpha")}<input required type="number" min=".0001" max=".4999" step="any" value={Number.isNaN(alpha) ? "" : alpha} onChange={event => setAlpha(event.target.valueAsNumber)} /></label>
      <label>{tr("Consecutive exceedances")}<input required type="number" min="1" step="1" value={Number.isNaN(persistence) ? "" : persistence} onChange={event => setPersistence(event.target.valueAsNumber)} /></label>
      {parameter && <label>{tr(parameter.label)}<input required type="number" min={parameter.min} max={parameter.max} step="any"
        value={parameterValue === undefined ? parameter.initial : Number.isNaN(parameterValue) ? "" : parameterValue}
        onChange={event => setParameterValue(event.target.valueAsNumber)} /></label>}
    </div>
    <label className="replay-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
      {tr("I confirm that the selected training period represents normal operation.")}</label>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    <button type="submit" className="ws-primary" disabled={busy || !confirmed || signals.length < (algorithm === "pca-q" ? 2 : 1)}>
      {busy ? tr("Preparing replay…") : tr("Prepare replay")}
    </button>
  </form>;
}

function alarmBands(series: ObservationSeries): AlarmBand[] {
  const bands: AlarmBand[] = [];
  series.states.forEach((state, index) => {
    if (state !== "alarm") return;
    const time = series.times[index];
    if (index > 0 && series.states[index - 1] === "alarm") {
      bands[bands.length - 1].end = time;
    } else {
      bands.push({ start: time, end: time });
    }
  });
  return bands;
}

function ReplayDashboard({ dataset, session, path, workspaceId }: {
  dataset: Dataset; session: Session; path: string; workspaceId: string;
}) {
  const axis = dataset.metadata.time;
  const stamp = (time: number) => timeLabel(axis, time);
  const [frame, setFrame] = useState<Frame | null>(null);
  const latest = useRef<Frame | null>(null);
  const playhead = useRef(session.start);
  const [position, setPosition] = useState(session.start);
  const [draft, setDraft] = useState<number | null>(null);
  const [speed, setSpeed] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState(0);
  const [shownSignal, setShownSignal] = useState(session.config.signals[0]);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [incidentId, setIncidentId] = useState("");
  const playbackRequest = useRef<AbortController | null>(null);
  function move(at: number) { playhead.current = at; setPosition(at); }
  function show(data: Frame | null) { latest.current = data; setFrame(data); }
  function pause() { playbackRequest.current?.abort(); setPlaying(false); }

  useEffect(() => {
    if (!playing) return;
    const controller = new AbortController();
    playbackRequest.current = controller;
    const started = performance.now(), anchor = playhead.current;
    let nextTime = latest.current ? latest.current.nextTime : session.start;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      if (controller.signal.aborted) return;
      const at = Math.min(session.end, anchor + (performance.now() - started) * speed / 1000);
      try {
        if (nextTime !== null && at >= nextTime) {
          const data = await api<Frame>(`${path}/frame`, { at }, "POST", controller.signal);
          if (controller.signal.aborted) return;
          nextTime = data.nextTime;
          show(data);
          setPage(0);
        }
        move(at);
        if (nextTime === null) setPlaying(false);
        else timer = setTimeout(tick, 150);
      } catch (failure) {
        if (!controller.signal.aborted) { setError(message(failure)); setPlaying(false); }
      }
    }
    void tick();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [playing, path, session.start, session.end, speed]);

  async function action(work: () => Promise<void>) {
    pause(); setBusy(true); setError("");
    try { await work(); }
    catch (failure) { setError(message(failure)); }
    finally { setBusy(false); }
  }
  function seek(at: number, alarmPage = 0) {
    void action(async () => {
      const data = await api<Frame>(`${path}/frame`, { at, alarmPage });
      setDraft(null); move(at); show(data); setPage(alarmPage);
      setEvidence(null); setIncidentId("");
    });
  }
  function start() {
    setError(""); setDraft(null); setEvidence(null); setIncidentId("");
    if (page !== 0) {
      void action(async () => {
        show(await api<Frame>(`${path}/frame`, { at: playhead.current }));
        setPage(0); setPlaying(true);
      });
    } else setPlaying(true);
  }
  function restart() {
    pause(); show(null); move(session.start); setPage(0);
    setDraft(null); setError(""); setEvidence(null); setIncidentId("");
  }
  function inspect(alarmId: number) {
    if (!frame) return;
    void action(async () => {
      setEvidence(null); setIncidentId("");
      setEvidence(await api<Evidence>(`${path}/evidence`, { alarmId, through: frame.through }));
    });
  }
  function preserve() {
    if (!frame || !evidence) return;
    void action(async () => {
      const incident = await api<Incident>(`${path}/incident`, { alarmId: evidence.alarm.id, through: frame.through });
      setIncidentId(incident.id);
    });
  }
  function exportReplay() {
    if (!frame) return;
    void action(async () => {
      const result = await api<unknown>(`${path}/export`, { through: frame.through, playbackSpeed: speed });
      downloadFile(`l5-replay-${session.id.slice(0, 8)}.json`, JSON.stringify(result, null, 2));
    });
  }

  const last = frame ? frame.series.times.length - 1 : -1;
  const decision = frame?.series.states[last];
  const finished = frame?.nextTime === null;
  const mode = playing ? "Playing" : finished ? "Replay complete" : frame ? "Paused" : "Ready";
  const bands = frame ? alarmBands(frame.series) : [];
  const currentTime = frame?.series.times[last];
  return <>
    <section className="ws-panel replay-console">
      <div className="replay-heading"><div><div className="ws-kicker">{tr("REPLAY CLOCK")}</div><h2>{dataset.name}</h2></div>
        <span role="status" className={`replay-state replay-state-${decision || "ready"}`}>{decision ? tr(decisions[decision]) : tr("Waiting for observations")}</span>
      </div>
      <div className="ws-inline replay-controls">
        <button type="button" className="ws-primary" disabled={busy || finished} onClick={playing ? pause : start}>
          {tr(playing ? "Pause" : frame ? "Resume" : "Start")}
        </button>
        <button type="button" disabled={busy || (!frame && !playing)} onClick={restart}>{tr("Restart")}</button>
        <label className="ws-inline">{tr("Playback speed")}
          <select value={speed} onChange={event => setSpeed(Number(event.target.value))}>
            {speedOptions.map(rate => <option key={rate} value={rate}>{number(rate)}×</option>)}
          </select>
        </label>
        <span className="ws-muted">{tr(mode)} · {tr("{0} / {1} observations", { 0: frame?.through ?? 0, 1: session.sampleCount })}</span>
        <button type="button" className="replay-export" disabled={busy || !frame} onClick={exportReplay}>{tr("Export replay JSON ↓")}</button>
      </div>
      <div className="replay-scrubber">
        <label>{tr("Playhead")} <output>{stamp(draft ?? position)}</output>
          <input type="range" aria-label={tr("Playhead")} min={session.start} max={session.end} step="any" value={draft ?? position}
            disabled={busy || session.start === session.end} aria-valuetext={stamp(draft ?? position)}
            onChange={event => { pause(); setDraft(Number(event.target.value)); }} />
        </label>
        <button type="button" disabled={busy || draft === null} onClick={() => draft !== null && seek(draft)}>{tr("Seek")}</button>
      </div>
      {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
      <div className="replay-metrics">
        <div><span>{tr("Last observation")}</span><strong>{currentTime === undefined ? "—" : stamp(currentTime)}</strong></div>
        <div><span>{tr(detectors[session.config.algorithm])}</span><strong>{reading(frame?.series.scores[last])}</strong></div>
        <div><span>{tr("Threshold")}</span><strong>{number(session.threshold)}</strong></div>
        <div><span>{tr("Fit / calibration samples")}</span><strong>{session.fitSamples} / {session.calibrationSamples}</strong></div>
      </div>
    </section>
    {frame && <section className="ws-panel">
      <div className="replay-heading"><div><h2>{tr("Process timeline")}</h2><p className="ws-muted">{tr("Latest 360 observations · shaded bands mark active alarms.")}</p></div>
        <label>{tr("Chart signal")}<select value={shownSignal} onChange={event => setShownSignal(event.target.value)}>
          {session.config.signals.map(name => <option key={name} value={name}>{namedSignal(dataset, name)}</option>)}
        </select></label>
      </div>
      <div className="replay-metrics replay-readings">
        {session.config.signals.map(name => <button type="button" key={name} aria-pressed={name === shownSignal} onClick={() => setShownSignal(name)}>
          <span>{namedSignal(dataset, name)}</span><strong>{reading(frame.series.values[name][last])}</strong>
        </button>)}
      </div>
      <ReplayPlots series={frame.series} dataset={dataset} signal={shownSignal} threshold={session.threshold} bands={bands} selectedTime={currentTime} />
    </section>}
    <section className="ws-panel">
      <div className="replay-heading"><h2>{tr("Alarm log")}</h2><span className="ws-muted">{tr("{0} alarms observed", { 0: frame?.alarmCount ?? 0 })}</span></div>
      {frame?.alarms.length ? <>
        <div className="ws-table-scroll"><table className="replay-table">
          <thead><tr>{["Onset", "Status", "Observed span", "Peak score", "Top contributing signals", "Evidence"].map(label => <th key={label} scope="col">{tr(label)}</th>)}</tr></thead>
          <tbody>{frame.alarms.map(alarm => <tr key={alarm.id}>
            <td>{stamp(alarm.start)}</td><td>{tr(alarmStatuses[alarm.status])}</td><td>{number(alarm.durationSeconds)} s</td>
            <td>{number(alarm.peakScore)}</td><td>{alarm.signals.map(name => namedSignal(dataset, name)).join(", ")}</td>
            <td><button type="button" disabled={busy} aria-pressed={evidence?.alarm.id === alarm.id} onClick={() => inspect(alarm.id)}>{tr("Inspect")}</button></td>
          </tr>)}</tbody>
        </table></div>
        {frame.alarmCount > session.alarmPageSize && <div className="ws-inline replay-pagination">
          <button type="button" disabled={busy || playing || page === 0} onClick={() => seek(position, page - 1)}>{tr("Newer alarms")}</button>
          <button type="button" disabled={busy || playing || (page + 1) * session.alarmPageSize >= frame.alarmCount} onClick={() => seek(position, page + 1)}>{tr("Earlier alarms")}</button>
        </div>}
      </> : <p className="ws-muted">{tr("No alarms observed at this replay position.")}</p>}
    </section>
    {evidence && <AlarmEvidence evidence={evidence} dataset={dataset} threshold={session.threshold} shownSignal={shownSignal}
      incidentId={incidentId} workspaceId={workspaceId} busy={busy} onPreserve={preserve} />}
  </>;
}

function ReplayPlots({ series, dataset, signal, threshold, bands, selectedTime }: {
  series: ObservationSeries; dataset: Dataset; signal: string; threshold: number; bands: AlarmBand[]; selectedTime?: number;
}) {
  const axis = dataset.metadata.time;
  return <>
    <Plot times={series.times} values={series.scores} segmentIds={series.scoreSegments} axis={axis} title={tr("Detector score")}
      threshold={threshold} intervals={bands} selectedTime={selectedTime} color="#e2bc75" />
    <Plot times={series.times} values={series.values[signal]} segmentIds={series.signalSegments[signal]} axis={axis}
      title={namedSignal(dataset, signal)} intervals={bands} selectedTime={selectedTime} />
  </>;
}

function AlarmEvidence({ evidence, dataset, threshold, shownSignal, incidentId, workspaceId, busy, onPreserve }: {
  evidence: Evidence; dataset: Dataset; threshold: number; shownSignal: string; incidentId: string; workspaceId: string; busy: boolean; onPreserve: () => void;
}) {
  const { alarm, series } = evidence;
  const axis = dataset.metadata.time;
  const peak = alarm.peakIndex - series.first;
  return <section className="ws-panel replay-evidence" aria-label={tr("Alarm evidence")}>
    <div className="replay-heading"><div><div className="ws-kicker">{tr("ALARM EVIDENCE")}</div>
      <h2>{timeLabel(axis, alarm.start)} · {tr(alarmStatuses[alarm.status])}</h2>
      <p>{tr("Onset to last alarm observation")} {timeLabel(axis, alarm.start)} → {timeLabel(axis, alarm.end)}</p>
      {alarm.transitionTime !== null && <p>{tr(alarm.status === "recovered" ? "Recovery observed at" : "Coverage lost at")} {timeLabel(axis, alarm.transitionTime)}</p>}
    </div>{incidentId ? <a className="ws-primary" href={`#/workspaces/${workspaceId}/incidents/${incidentId}`}>{tr("Open saved incident ↗")}</a>
      : <button type="button" className="ws-primary" disabled={busy} onClick={onPreserve}>{tr("Save alarm as incident")}</button>}</div>
    <div className="replay-metrics">
      <div><span>{tr("Peak time")}</span><strong>{timeLabel(axis, alarm.peakTime)}</strong></div>
      <div><span>{tr("Peak score")}</span><strong>{number(alarm.peakScore)}</strong></div>
      <div><span>{tr("Observed span")}</span><strong>{number(alarm.durationSeconds)} s</strong></div>
    </div>
    <div className="ws-table-scroll"><table className="replay-table">
      <thead><tr><th scope="col">{tr("Signal")}</th><th scope="col">{tr("Measurement at peak")}</th><th scope="col">{tr("Contribution at peak")}</th></tr></thead>
      <tbody>{alarm.contributions?.map(item => <tr key={item.signal}><th scope="row">{namedSignal(dataset, item.signal)}</th>
        <td>{reading(series.values[item.signal][peak])}</td><td>{number(item.value)}</td></tr>)}</tbody>
    </table></div>
    <p className="ws-muted">{tr("Detector contributions describe statistical deviations. The charts show up to 12 observed rows on either side of the peak.")}</p>
    <ReplayPlots series={series} dataset={dataset} signal={alarm.signals[0] || shownSignal} threshold={threshold} bands={[alarm]} selectedTime={alarm.peakTime} />
  </section>;
}
