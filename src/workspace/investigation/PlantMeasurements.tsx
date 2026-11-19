import { useState, type ReactNode } from "react";
import { Plot, type Overlay } from "../Charts";
import { number, type Series, type Signal, type TimeAxis } from "../types";

export type OperatingPlot = { title: string; signals: Pick<Signal, "name" | "unit" | "device">[]; stepAfter?: boolean };

const colors = ["#b5ed9a", "#e2bc75"];
const seconds = (time: number) => `${time.toLocaleString("en")} s`;

export function PlantMeasurements({ plots, measured, matched, onset, action, interventionName, children }: {
  plots: OperatingPlot[]; measured: Series; matched?: Series; onset: number; action: number;
  interventionName: string; children?: ReactNode;
}) {
  const [cursor, setCursor] = useState<number>();
  const start = measured.times[0], end = measured.times.at(-1)!;
  const axis: TimeAxis = { kind: "numeric", column: null, origin: null, start, end };
  const sameTick = matched && onset === action;
  const markers = [{ time: onset, label: sameTick ? "Disturbance and intervention" : "Disturbance" },
    ...(matched && !sameTick ? [{ time: action, label: "Intervention", annotation: true, labelRow: 1 }] : [])];
  const valueAt = (series: Series, name: string) => {
    const value = cursor === undefined ? undefined : series.values[name]?.[series.times.indexOf(cursor)];
    return value == null ? "—" : number(value);
  };
  return <section className="ws-panel ws-plant-measurements" aria-label="Operating measurements">
    <div className="ws-section-heading"><h2>Operating measurements</h2>{children}</div>
    <p className="ws-muted">Disturbance at {seconds(onset)}{matched && ` · ${interventionName} at ${seconds(action)}`}</p>
    <div className="ws-inline ws-plant-legend" aria-label="Trajectory styles">
      <span><i />Baseline · simulated measurements</span>
      {matched && <span><i className="ws-plant-dashed" />Matched intervention · counterfactual</span>}
      {cursor !== undefined && <span>Selected time {seconds(cursor)}</span>}
    </div>
    {plots.map(plot => {
      const signals = plot.signals.filter(signal => measured.values[signal.name]);
      if (!signals.length) return null;
      const unit = signals[0].unit === "Deg C" ? "°C" : signals[0].unit === "m3/hr" ? "m³/h" : signals[0].unit;
      const title = `${plot.title} (${unit})`;
      const label = (signal: typeof signals[number]) => plot.signals.length > 1 ? signal.device || signal.name : plot.title;
      const overlays: Overlay[] = signals.slice(1).map((signal, index) => ({
        times: measured.times, values: measured.values[signal.name], segmentIds: measured.segmentIds?.[signal.name],
        title: `${label(signal)} baseline`, color: colors[index + 1],
      }));
      if (matched) signals.forEach((signal, index) => {
        const values = matched.values[signal.name];
        if (values) overlays.push({ times: matched.times, values, segmentIds: matched.segmentIds?.[signal.name],
          title: `${label(signal)} intervention`, color: colors[index], dash: "5 4" });
      });
      return <div className="ws-plant-chart" key={plot.title}>
        <Plot title={title} times={measured.times} axis={axis} timeDomain={[start, end]} values={measured.values[signals[0].name]}
          segmentIds={measured.segmentIds?.[signals[0].name]} color={colors[0]} overlays={overlays}
          markers={markers} selectedTime={cursor} onSelectTime={setCursor} stepAfter={plot.stepAfter} height={150} formatTime={seconds} showIsolatedPoints />
        {(plot.signals.length > 1 || cursor !== undefined) && <div className="ws-inline ws-plant-legend">
          {signals.map((signal, index) => <span key={signal.name}><i style={{ borderColor: colors[index] }} />{label(signal)}
            {cursor !== undefined && ` · Baseline ${valueAt(measured, signal.name)} ${unit}${matched ? ` · Intervention ${valueAt(matched, signal.name)} ${unit}` : ""}`}</span>)}
        </div>}
      </div>;
    })}
  </section>;
}
