import { useState } from "react";
import { t as tr } from "../i18n";
import { Plot } from "./Charts";
import { alarmTime } from "./AlarmEvidence";
import { incidentAxis, number, type IncidentAxis } from "./types";
import type { AlarmFloodAxis } from "./alarmTypes";

export function AlarmLoad({ axis, flood, datasetNames }: { axis: IncidentAxis; flood: AlarmFloodAxis; datasetNames: Map<string, string> }) {
  const [showWindows, setShowWindows] = useState(false);
  const [page, setPage] = useState(0);
  const bins = flood.bins.slice(page * 30, (page + 1) * 30);
  const last = flood.bins.at(-1);
  const times = last ? [...flood.bins.map(bin => bin.start), last.end] : [];
  const groupArrivals = last ? [...flood.bins.map(bin => bin.groupArrivals), last.groupArrivals] : [];
  const value = (n: number | null) => n == null ? "—" : number(n);
  return <section className="ws-panel alarm-load" aria-label={tr("Alarm load")}>
    <div className="alarm-section-heading"><h2>{tr("Alarm load")}</h2><span className="ws-muted">{tr("{0} s arrival windows", { 0: number(flood.windowSeconds) })}</span></div>
    <div className="alarm-facts">
      <div><span>{tr("Peak arrivals / window")}</span><strong>{flood.peakArrivalCount.toLocaleString()}</strong><small>{tr("{0} per hour at peak", { 0: number(flood.peakArrivalsPerHour) })}</small></div>
      <div><span>{tr("Peak concurrent alarms")}</span><strong>{flood.peakConcurrent.toLocaleString()}</strong><small>{tr("{0} repeat arrivals", { 0: flood.repeatedEventCount.toLocaleString() })}</small></div>
      <div><span>{tr("Mean / total alarm duration")}</span><strong>{value(flood.meanDurationSeconds)} / {value(flood.totalDurationSeconds)} s</strong></div>
      <div><span>{tr("Mean acknowledgement delay")}</span><strong>{flood.meanAcknowledgementDelaySeconds == null ? "—" : `${value(flood.meanAcknowledgementDelaySeconds)} s`}</strong><small>{tr("{0} acknowledged alarms", { 0: flood.acknowledgedCount.toLocaleString() })}</small></div>
    </div>
    <p className="ws-muted">{tr("Fixed windows start at {0}. Arrivals use event starts. Hourly rates normalize counts by the full window length. Acknowledgement delay starts at session creation.", { 0: alarmTime(axis, flood.anchor) })}</p>
    {last && <><div className="alarm-legend"><span>{tr("Source alarm arrivals")}</span><span>{tr("Correlated group arrivals")}</span></div>
      <Plot times={times} values={[...flood.bins.map(bin => bin.arrivals), last.arrivals]} title={tr("Arrivals per window")} axis={incidentAxis(axis)}
        timeDomain={[flood.anchor, last.end]} color="#e9927d" stepAfter
        overlays={[{ times, values: groupArrivals, title: tr("Correlated group arrivals"), color: "#b5ed9a" }]} />
    </>}
    {times.length > 0 && <details onToggle={e => setShowWindows(e.currentTarget.open)}>
      <summary>{tr("Window counts")}</summary>
      {showWindows && <><div className="ws-table-scroll"><table>
        <thead><tr>{["Window start", "Window end", "Windows", "Source alarms", "Correlated groups", "Arrivals per hour", "Peak concurrent alarms"].map(label => <th key={label}>{tr(label)}</th>)}</tr></thead>
        <tbody>{bins.map(bin => <tr key={bin.start}><td>{alarmTime(axis, bin.start)}</td><td>{alarmTime(axis, bin.end)}</td><td>{bin.windowCount.toLocaleString()}</td>
          <td>{bin.arrivals.toLocaleString()}</td><td>{bin.groupArrivals.toLocaleString()}</td><td>{number(bin.arrivalsPerHour)}</td><td>{bin.peakConcurrent.toLocaleString()}</td></tr>)}</tbody>
      </table></div><AlarmPages page={page} pages={Math.ceil(flood.bins.length / 30)} setPage={setPage} /></>}
    </details>}
    <details>
      <summary>{tr("Alarm distribution by signal and equipment")}</summary>
      <div className="alarm-distributions">
        <Distribution title={tr("Signal")} values={flood.bySignal.map(item => [`${datasetNames.get(item.datasetId) || item.datasetId} · ${item.signal}`, item.count])} />
        <Distribution title={tr("Equipment")} values={flood.byEquipment.map(item => [item.equipment ?? tr("Unmapped equipment"), item.count])} />
      </div>
    </details>
  </section>;
}

function Distribution({ title, values }: { title: string; values: [string, number][] }) {
  return <div className="ws-table-scroll"><table><thead><tr><th>{title}</th><th>{tr("Source alarms")}</th></tr></thead>
    <tbody>{values.map(([label, count], index) => <tr key={index}><td>{label}</td><td>{count.toLocaleString()}</td></tr>)}</tbody></table>
    {values.length === 0 && <p className="ws-muted">{tr("No entries")}</p>}</div>;
}

export function AlarmPages({ page, pages, setPage }: { page: number; pages: number; setPage: (value: number) => void }) {
  return pages > 1 && <div className="alarm-pagination">
    <button className="ws-outlined" type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>{tr("Previous page")}</button>
    <span className="ws-muted">{tr("Page {0} of {1}", { 0: page + 1, 1: pages })}</span>
    <button className="ws-outlined" type="button" disabled={page === pages - 1} onClick={() => setPage(page + 1)}>{tr("Next page")}</button>
  </div>;
}
