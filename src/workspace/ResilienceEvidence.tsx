import { t as tr } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { useMemo, useState } from "react";
import { Plot } from "./Charts";
import { fraction } from "./ResilienceCampaign";
import { FaultTimeline, faultName, signalName, targetName } from "./ResilienceScenario";
import { number, type TimeAxis } from "./types";
import type { Burden, CaseDetail, Evaluation, Simulation } from "./resilienceTypes";

const seconds = (value: number | null | undefined) => value == null ? "—" : `${number(value)} s`;

function AlarmBurden({ label, burden }: { label: string; burden: Burden }) {
  return <tr><th scope="row">{label}</th><td>{burden.alarmEvents}</td><td>{burden.alarmSamples} / {burden.observedSamples}</td>
    <td>{fraction(burden.alarmFraction)}</td><td>{seconds(burden.alarmDuration)}</td></tr>;
}

function DetectorEvidence({ evaluation, axis, markers, selectedTime, onSelectTime }: {
  evaluation: Evaluation;
  axis: TimeAxis;
  markers: { time: number; label: string }[];
  selectedTime: number | undefined;
  onSelectTime: (time: number) => void;
}) {
  const { analysis, metrics } = evaluation;
  const scores = analysis.scores.map((score, index) => analysis.states?.[index] === "abstain" ? null : score);
  const suppression = metrics.suppression;
  return <>
    <div className="ws-section-heading"><h3>{tr("Detector evidence")}</h3><span className="ws-muted">{tr(analysis.algorithmLabel)} · {number(analysis.durationMs)} ms</span></div>
    <div className="ws-stats">
      <div><strong>{metrics.detectedEvents} / {metrics.totalEvents}</strong><span>{tr("Events matched")}</span></div>
      <div><strong>{fraction(metrics.coverage)}</strong><span>{tr("Coverage")}</span></div>
      <div><strong>{seconds(metrics.meanDelay)}</strong><span>{tr("Mean detection delay")}</span></div>
      <div><strong>{metrics.totalEvents ? tr(metrics.presenceDetected ? "Yes" : "No") : "—"}</strong><span>{tr("Any fault detected")}</span></div>
    </div>
    <Plot times={analysis.times} values={scores} title={tr("Detector scores and alarm intervals")} axis={axis}
      threshold={analysis.threshold} intervals={analysis.intervals} markers={markers} selectedTime={selectedTime}
      onSelectTime={onSelectTime} timeDomain={[axis.start, axis.end]} />
    <details open><summary>{tr("Event scoring and detection latency")}</summary>
      <p className="ws-notice">{tr("An alarm onset can match one active fault event. The match indicates detection timing, without assigning a fault cause.")}</p>
      <div className="ws-table-scroll"><table>
        <thead><tr>{["Fault event", "Fault onset", "Observed samples", "Matched alarm", "Detection delay"].map(label => <th key={label}>{tr(label)}</th>)}</tr></thead>
        <tbody>{metrics.events.map(event => <tr key={event.id}>
          <th scope="row">{faultName(event.type)} · {targetName(event.target)}<small>{event.id}</small></th>
          <td>{seconds(event.onset)}</td><td>{event.observedSamples}</td>
          <td className={!event.detected ? "ws-coral" : undefined}>{event.detected ? seconds(event.firstDetection) : tr("Missed")}</td>
          <td>{seconds(event.delay)}</td>
        </tr>)}</tbody>
      </table></div>
      {!metrics.events.length && <p className="ws-muted">{tr("Healthy control. No events to score.")}</p>}
      {metrics.simultaneousSamples > 0 && <p className="ws-notice">{tr("{0} of {1} overlapping samples were scored, with {2} alarm samples.", {
        0: metrics.simultaneousObservedSamples, 1: metrics.simultaneousSamples, 2: metrics.simultaneousAlarmSamples,
      })}</p>}
      {suppression && <>
        <h3>{tr("Paired isolated-fault comparison")}</h3>
        <p className="ws-notice">{tr("{0} events lost alarm presence and {1} lost their distinct alarm match when combined.", { 0: suppression.lostPresenceEvents, 1: suppression.lostMatches })}</p>
        <div className="ws-table-scroll"><table>
          <thead><tr>{["Fault event", "Isolated alarm presence", "Combined alarm presence", "Isolated delay", "Combined delay"].map(label => <th key={label}>{tr(label)}</th>)}</tr></thead>
          <tbody>{suppression.events.map(event => <tr key={event.id}>
            <th scope="row">{event.id}</th><td>{tr(event.isolatedPresence ? "Yes" : "No")}</td>
            <td>{tr(event.combinedPresence ? "Yes" : "No")}</td><td>{seconds(event.isolatedDelay)}</td><td>{seconds(event.combinedDelay)}</td>
          </tr>)}</tbody>
        </table></div>
      </>}
      <h3>{tr("Alarm burden")}</h3>
      <div className="ws-table-scroll"><table>
        <thead><tr>{["Window", "Alarm starts", "Alarm samples / observed", "Alarm fraction", "Alarm duration"].map(label => <th key={label}>{tr(label)}</th>)}</tr></thead>
        <tbody>{metrics.normal && <AlarmBurden label={tr("Normal operation")} burden={metrics.normal} />}
          {metrics.preFault && <AlarmBurden label={tr("Pre-fault")} burden={metrics.preFault} />}</tbody>
      </table></div>
    </details>
  </>;
}

export function CaseError({ detail }: { detail: CaseDetail }) {
  if (!detail.error) return null;
  return <p className="ws-error" role="alert">{errorMessage(detail.error)}</p>;
}

export function EvidenceView({ title, simulation, evaluation, busy, exported, onExport, onExplore, onIncident }: {
  title: string;
  simulation: Simulation;
  evaluation?: Evaluation | null;
  busy: boolean;
  exported: boolean;
  onExport: () => void;
  onExplore: () => void;
  onIncident: () => void;
}) {
  const { observations, signals, scenario, schedule, truth } = simulation;
  const [signalKey, setSignal] = useState(signals[0]?.key ?? "");
  const [sampleIndex, setSampleIndex] = useState(0);
  const [selectedFault, setSelectedFault] = useState("");
  const [packetOffset, setPacketOffset] = useState(0);
  const [packetsOpen, setPacketsOpen] = useState(false);
  const signal = signals.find(item => item.key === signalKey) ?? signals[0];
  const observation = observations[Math.min(sampleIndex, observations.length - 1)];
  const physicalTimes = useMemo(() => truth.physical.map(row => row.t), [truth.physical]);
  const observationTimes = useMemo(() => observations.map(row => row.t), [observations]);
  const axis: TimeAxis = { kind: "numeric", column: "t", origin: null, start: 0, end: scenario.duration };
  const plotted = useMemo(() => {
    if (!signal) return { physical: [], measured: [], quality: new Map<string, number>() };
    const quality = new Map<string, number>();
    const measured = observations.map(row => {
      const state = row.quality[signal.key] ?? "unavailable";
      quality.set(state, (quality.get(state) ?? 0) + 1);
      return row.values[signal.key] ?? null;
    });
    return { physical: truth.physical.map(row => row[signal.key] ?? null), measured, quality };
  }, [signal, observations, truth.physical]);
  const packets = useMemo(() => packetsOpen ? simulation.observation_packets.filter(packet => packet.signal === signal?.key) : [],
    [simulation.observation_packets, signal, packetsOpen]);
  const detections = new Map(evaluation?.metrics.events.flatMap(event => event.firstDetection == null ? [] : [[event.id, event.firstDetection] as const]));
  const markers = [...new Set(schedule.flatMap(fault => fault.intervals[0]?.start ?? []))]
    .map(time => ({ time, label: tr("Fault onset") }));
  const event = schedule.find(fault => fault.id === selectedFault) ?? schedule[0];
  function selectTime(time: number) {
    const at = observations.findIndex(row => row.t >= time);
    setSampleIndex(at < 0 ? Math.max(0, observations.length - 1) : at);
  }
  return <section className="ws-panel resilience-evidence">
    <div className="ws-section-heading"><h2>{title}</h2><span className="ws-muted">{tr("Model version")} {simulation.model_version} · {tr("Random seed")} {scenario.seed}</span></div>
    <div className="resilience-actions">
      <button type="button" className="ws-outlined" onClick={onExport} disabled={busy || exported}>{tr(exported ? "Dataset exported" : "Export observations as Dataset")}</button>
      <button type="button" className="ws-outlined" onClick={onExplore} disabled={busy}>{tr("Open Signal Explorer ↗")}</button>
      <button type="button" className="ws-outlined" onClick={onIncident} disabled={busy}>{tr("Link to Incident")}</button>
    </div>
    <div className="ws-section-heading"><h3>{tr("Ground-truth fault timeline")}</h3></div>
    <FaultTimeline faults={schedule} duration={scenario.duration} selectedId={event?.id} onSelect={setSelectedFault} detections={detections} />
    {event && truth.severities[event.id] && <Plot times={physicalTimes.slice(0, truth.severities[event.id].length)} values={truth.severities[event.id]}
      title={`${tr("Applied fault severity")} · ${event.id}`} axis={axis} timeDomain={[axis.start, axis.end]} domain={[0, 1]} selectedTime={observation?.t} onSelectTime={selectTime} />}
    {signal && <>
      <div className="ws-section-heading"><h3>{tr("Physical vs. measured trajectories")}</h3></div>
      <label className="resilience-signal-select">{tr("Displayed signal")}<select value={signal.key} onChange={event => { setSignal(event.target.value); setPacketOffset(0); }}>
        {signals.map(item => <option value={item.key} key={item.key}>{signalName(item)} ({item.unit})</option>)}
      </select></label>
      <div className="resilience-legend"><span><i />{tr("Physical truth")}</span><span><i />{tr("Delivered measurements")}</span></div>
      <Plot times={physicalTimes} values={plotted.physical} title={`${signalName(signal)} (${signal.unit})`} axis={axis}
        color="#8cbfe8" overlays={[{ times: observationTimes, values: plotted.measured, title: tr("Delivered measurements"), color: "#b5ed9a" }]}
        intervals={evaluation?.analysis.intervals} markers={markers} selectedTime={observation?.t} onSelectTime={selectTime}
        timeDomain={[axis.start, axis.end]} />
      <div className="resilience-quality">
        <h3>{tr("Observation quality")}</h3>
        <dl>{[...plotted.quality].map(([state, count]) => <div key={state}><dt>{tr(state)}</dt><dd>{count.toLocaleString()}</dd></div>)}</dl>
      </div>
      {observation && <details open><summary>{tr("Observation readout")} · {seconds(observation.t)}</summary>
        <label>{tr("Acquisition frame")}<input type="range" min={0} max={Math.max(0, observations.length - 1)} step={1} value={sampleIndex}
          onChange={event => setSampleIndex(Number(event.target.value))} /></label>
        <div className="ws-table-scroll"><table>
          <thead><tr>{["Signal", "Measurement", "Quality", "Source timestamp", "Acquisition timestamp"].map(label => <th key={label}>{tr(label)}</th>)}</tr></thead>
          <tbody>{signals.map(item => {
            const value = observation.values[item.key];
            return <tr key={item.key}><th scope="row">{signalName(item)}</th><td>{value == null ? "—" : `${number(value)} ${item.unit}`}</td>
              <td>{tr(observation.quality[item.key] ?? "unavailable")}</td><td>{seconds(observation.source_times[item.key])}</td><td>{seconds(observation.acquisition_times[item.key])}</td></tr>;
          })}</tbody>
        </table></div>
      </details>}
      <details onToggle={event => setPacketsOpen(event.currentTarget.open)}>
        <summary>{tr("Raw observation packets")}</summary>
        {packetsOpen && <>
          <p className="ws-muted">{tr("Packets are listed by scheduled sample time. Missing acquisition timestamps indicate packets that were never delivered.")}</p>
          <div className="ws-table-scroll"><table>
            <thead><tr>{["Scheduled sample time", "Source timestamp", "Acquisition timestamp", "Measurement", "Quality"].map(label => <th key={label}>{tr(label)}</th>)}</tr></thead>
            <tbody>{packets.slice(packetOffset, packetOffset + 16).map(packet => <tr key={packet.sample_time}>
              <th scope="row">{seconds(packet.sample_time)}</th><td>{seconds(packet.source_time)}</td><td>{seconds(packet.acquisition_time)}</td>
              <td>{packet.value == null ? "—" : `${number(packet.value)} ${signal.unit}`}</td><td>{packet.flags.length ? packet.flags.map(flag => tr(flag)).join(" · ") : tr(packet.quality)}</td>
            </tr>)}</tbody>
          </table></div>
          <div className="resilience-actions">
            <button type="button" className="ws-outlined" disabled={packetOffset === 0} onClick={() => setPacketOffset(offset => Math.max(0, offset - 16))}>{tr("Previous packets")}</button>
            <span className="ws-muted">{tr("{0} / {1} packets", { 0: Math.min(packetOffset + 16, packets.length), 1: packets.length })}</span>
            <button type="button" className="ws-outlined" disabled={packetOffset + 16 >= packets.length} onClick={() => setPacketOffset(offset => offset + 16)}>{tr("Next packets")}</button>
          </div>
        </>}
      </details>
    </>}
    {evaluation && <DetectorEvidence evaluation={evaluation} axis={axis} markers={markers} selectedTime={observation?.t} onSelectTime={selectTime} />}
    <details><summary>{tr("Saved configuration")}</summary><pre>{JSON.stringify({ scenario, model_version: simulation.model_version, ...(evaluation ? { detector: evaluation.analysis.config } : {}) }, null, 2)}</pre></details>
  </section>;
}
