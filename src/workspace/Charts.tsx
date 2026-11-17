import { errorMessage, t as tr } from "../lib/text";
import { memo, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { cachedSeries } from "./seriesCache";
import { namedSignal, number, timeLabel, type Dataset, type Interval, type TimeAxis } from "./types";

const W = 960, H = 190, L = 76, R = 18, T = 18, B = 32;
function plotIndexes(values: (number | null)[]) {
  if (values.length <= 1800) return values.map((_, i) => i);
  const result = new Set([0, values.length - 1]), step = Math.ceil(values.length / 450);
  for (let i = 0; i < values.length; i += step) {
    let min = i, max = i;
    for (let j = i; j < Math.min(i + step, values.length); j++) {
      if (values[j] == null) { result.add(j); continue; }
      if (values[min] == null || values[j]! < values[min]!) min = j;
      if (values[max] == null || values[j]! > values[max]!) max = j;
    }
    result.add(min); result.add(max);
  }
  return [...result].sort((a, b) => a - b);
}

type Overlay = { times: number[]; values: (number | null)[]; segmentIds?: number[]; title: string; color: string; dash?: string; points?: boolean };
type Band = { times?: number[]; lower: number[]; upper: number[]; title: string; color: string };
type Marker = { time: number; label: string; annotation?: boolean };
type TimeBand = { start: number; end: number; label: string; color: string };

export const Plot = memo(function Plot({
  times, values, title, axis, threshold, intervals = [], color = "#b5ed9a", domain,
  thresholdLabel = "Threshold", selectedTime, onSelectTime, onHoverTime, timeDomain,
  segmentIds, overlays = [], gaps = [], markers = [], bands = [], timeBands = [],
  showIsolatedPoints = false, stepAfter = false,
}: {
  times: number[]; values: (number | null)[]; title: string; axis: TimeAxis;
  threshold?: number; intervals?: Pick<Interval, "start" | "end">[]; color?: string;
  domain?: [number, number]; thresholdLabel?: string; selectedTime?: number;
  onSelectTime?: (time: number) => void; onHoverTime?: (time: number) => void;
  timeDomain?: [number, number]; segmentIds?: number[]; overlays?: Overlay[];
  gaps?: { start: number; end: number }[]; markers?: Marker[]; bands?: Band[];
  timeBands?: TimeBand[];
  showIsolatedPoints?: boolean; stepAfter?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (!times.length) return null;
  let low = Infinity, high = -Infinity;
  for (const line of [values, ...overlays.map(item => item.values), ...bands.flatMap(band => [band.lower, band.upper])]) {
    for (const value of line) if (value != null) { low = Math.min(low, value); high = Math.max(high, value); }
  }
  if (!Number.isFinite(low)) return <div className="ws-notice">{title}: no measured values in this window.</div>;
  if (domain) [low, high] = domain;
  if (threshold !== undefined) { low = Math.min(domain ? low : 0, low, threshold); high = Math.max(high, threshold); }
  const margin = Math.max((high - low) * .08, Math.abs(high) * .002, .001);
  low -= margin; high += margin;
  const [first, last] = timeDomain || [times[0], times[times.length - 1]], span = last - first || 1;
  const x = (t: number) => L + (t - first) / span * (W - L - R);
  const y = (v: number) => T + (high - v) / (high - low) * (H - T - B);
  const crossesGap = (start: number, end: number) => gaps.some(gap => gap.end > start && gap.start < end);
  function pathFor(ts: number[], vs: (number | null)[], ids?: number[]) {
    let connected = false, previousSegment: number | undefined, previousTime = -Infinity;
    const indexes = stepAfter ? vs.map((_, index) => index) : plotIndexes(vs);
    return indexes.map(i => {
      const value = vs[i];
      if (value == null) { connected = false; return ""; }
      // Overlay shading can include another source's gaps; each line's own
      // full-resolution segment identities determine whether it connects.
      const separated = !ids && crossesGap(previousTime, ts[i]);
      const canJoin = connected && !separated && (!ids || previousSegment === ids[i]);
      const px = x(ts[i]).toFixed(2), py = y(value).toFixed(2);
      const point = canJoin && stepAfter ? `H${px} V${py}` : `${canJoin ? "L" : "M"}${px},${py}`;
      connected = true; previousSegment = ids?.[i]; previousTime = ts[i]; return point;
    }).join(" ");
  }
  const active = hover != null && hover < times.length ? hover : null;
  return <figure className="ws-plot">
    <figcaption><span><i style={{ background: color }} />{title}</span><span className="ws-muted">{active == null ? tr("{0} displayed points", {0: times.length.toLocaleString("en")}) : `${timeLabel(axis, times[active])} · ${values[active] == null ? "missing" : number(values[active]!)}`}</span></figcaption>
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={tr("{0} time series{1}", {0: title, 1: threshold === undefined ? "" : tr(", threshold {0}", {0: number(threshold)})})} onClick={() => { if (hover != null && onSelectTime) onSelectTime(times[hover]); }}
      onPointerLeave={() => setHover(null)} onPointerMove={e => {
        const rect = e.currentTarget.getBoundingClientRect();
        const t = first + Math.max(0, Math.min(1, ((e.clientX - rect.left) / rect.width * W - L) / (W - L - R))) * span;
        let a = 0, b = times.length - 1;
        while (a < b) { const m = (a + b) >> 1; if (times[m] < t) a = m + 1; else b = m; }
        setHover(stepAfter && times[a] > t ? Math.max(0, a - 1) : a); onHoverTime?.(t);
      }}>
      <title>{title}{threshold !== undefined ? ` — ${thresholdLabel} ${number(threshold)}` : ""}</title>
      {[0, .5, 1].map(f => <g key={f}><line x1={L} x2={W - R} y1={T + f * (H - T - B)} y2={T + f * (H - T - B)} stroke="#30392d" strokeDasharray="3 5" /><text x={L - 10} y={T + f * (H - T - B) + 4} textAnchor="end">{number(high - f * (high - low))}</text></g>)}
      {intervals.filter(i => i.end >= first && i.start <= last).map((interval, i) => <rect key={i} x={x(Math.max(first, interval.start))} width={Math.max(2, x(Math.min(last, interval.end)) - x(Math.max(first, interval.start)))} y={T} height={H - T - B} fill="#e9927d" opacity=".14" />)}
      {gaps.filter(g => g.end >= first && g.start <= last).map((gap, i) => <rect key={`gap-${i}`} data-quality-gap="true" x={x(Math.max(first, gap.start))} width={Math.max(2, x(Math.min(last, gap.end)) - x(Math.max(first, gap.start)))} y={T} height={H - T - B} fill="#e2bc75" opacity=".13"><title>Sampling gap</title></rect>)}
      {timeBands.filter(band => band.end >= first && band.start <= last).map((band, i) => <rect key={`band-${i}`} x={x(Math.max(first, band.start))} width={Math.max(2, x(Math.min(last, band.end)) - x(Math.max(first, band.start)))} y={T} height={H - T - B} fill={band.color} opacity=".16"><title>{band.label}</title></rect>)}
      {threshold !== undefined && <><line x1={L} x2={W - R} y1={y(threshold)} y2={y(threshold)} stroke="#e2bc75" strokeDasharray="7 4" /><text x={W - R - 4} y={y(threshold) - 5} textAnchor="end" fill="#e2bc75">{thresholdLabel} {number(threshold)}</text></>}
      {markers.filter(m => m.time >= first && m.time <= last).map((m, index) => <g key={`${m.time}-${index}`} data-truth-onset={m.annotation ? undefined : m.time}><line x1={x(m.time)} x2={x(m.time)} y1={T} y2={H-B} stroke="#8cbfe8" strokeDasharray="3 3" /><text x={x(m.time)+4} y={T+10} fill="#8cbfe8">{m.label}</text></g>)}
      {bands.map(band => {
        const clock = band.times ?? times;
        const indexes = [...new Set([...plotIndexes(band.upper), ...plotIndexes(band.lower)])].sort((a, b) => a - b);
        const points = (selected: number[], bounds: number[]) =>
          selected.map(i => `${x(clock[i]).toFixed(2)},${y(bounds[i]).toFixed(2)}`);
        const polygon = [...points(indexes, band.upper), ...points(indexes.reverse(), band.lower)].join(" ");
        return <polygon key={band.title} data-uncertainty-band="true" points={polygon} fill={band.color} opacity=".18"><title>{band.title}</title></polygon>;
      })}
      <path d={pathFor(times, values, segmentIds)} fill="none" stroke={color} strokeWidth="1.7" vectorEffect="non-scaling-stroke" />
      {showIsolatedPoints && plotIndexes(values).map(index => {
        const value = values[index];
        if (value == null) return null;
        const connected = (a: number, b: number) => values[a] != null && values[b] != null &&
          (segmentIds ? segmentIds[a] === segmentIds[b] : !crossesGap(times[a], times[b]));
        return connected(index - 1, index) || connected(index, index + 1) ? null :
          <circle key={index} cx={x(times[index])} cy={y(value)} r="2.7" fill={color} />;
      })}
      {overlays.map(line => <path key={line.title} d={pathFor(line.times, line.values, line.segmentIds)} fill="none" stroke={line.color} strokeWidth="1.7" strokeDasharray={line.dash} vectorEffect="non-scaling-stroke"><title>{line.title}</title></path>)}
      {overlays.filter(line => line.points).map(line => <g key={line.title} data-measurement-points="true">{plotIndexes(line.values).filter(i => line.values[i] != null).map(i => <circle key={i} cx={x(line.times[i])} cy={y(line.values[i]!)} r="2" fill={line.color}><title>{line.title}: {number(line.values[i]!)}</title></circle>)}</g>)}
      {active != null && <line x1={x(times[active])} x2={x(times[active])} y1={T} y2={H - B} stroke="#d5dace" opacity=".5" />}
      {selectedTime !== undefined && selectedTime >= first && selectedTime <= last && <line data-selected-time={selectedTime} x1={x(selectedTime)} x2={x(selectedTime)} y1={T} y2={H - B} stroke="#e2bc75" strokeDasharray="4 3" />}
      <text x={L} y={H - 5}>{timeLabel(axis, first)}</text><text x={W - R} y={H - 5} textAnchor="end">{timeLabel(axis, last)}</text>
    </svg>
  </figure>;
});

export function SignalPlots({ dataset, signals, range, intervals, selectedTime, onSelectTime, markers, label = name => namedSignal(dataset, name) }: {
  dataset: Dataset; signals: string[]; range?: [number, number]; intervals?: Interval[]; selectedTime?: number;
  onSelectTime?: (time: number) => void; markers?: { time: number; label: string }[]; label?: (signal: string) => string;
}) {
  const start = range?.[0], end = range?.[1];
  const cache = useMemo(() => cachedSeries(dataset.id, start === undefined || end === undefined ? undefined : [start, end]), [dataset.id, start, end]);
  useSyncExternalStore(cache.subscribe, cache.snapshot, cache.snapshot);
  const allNames = dataset.metadata.columns.map(column => column.name);
  const small = dataset.metadata.rowCount <= 1600 && allNames.length <= 24;
  const wanted = JSON.stringify(signals.length && small ? allNames : signals);
  useEffect(() => {
    // Finish requests even if a signal is hidden meanwhile: the result warms its cache.
    void cache.load(JSON.parse(wanted));
  }, [cache, wanted]);
  if (!signals.length) return <p className="ws-muted">Select signals to plot.</p>;
  const preview = signals.map(name => cache.signals.get(name)).find(data => data && data.displayRows < data.sourceRows);
  return <div className="ws-signal-plots">{signals.map(name => {
    const data = cache.signals.get(name), error = cache.errors.get(name);
    return data ? <Plot key={name} times={data.times} values={data.values} segmentIds={data.segmentIds} gaps={dataset.metadata.quality?.gaps} title={label(name)} axis={dataset.metadata.time} markers={markers ?? (dataset.metadata.external?.faultOnsetSeconds == null ? [] : [{ time: dataset.metadata.external.faultOnsetSeconds, label: "Published fault onset" }])} intervals={intervals} selectedTime={selectedTime} onSelectTime={onSelectTime} /> :
      <figure className="ws-plot ws-plot-pending" key={name}><figcaption>{name}</figcaption><div className="ws-plot-placeholder">
        {error ? <div role="alert"><p>{errorMessage(error)}</p><button type="button" className="ws-outlined" onClick={() => void cache.load([name], true)}>Retry signal</button></div> : <span role="status">Loading{" "}{name}…</span>}
      </div></figure>;
  })}
    {preview && <p className="ws-muted">Overview preserves extrema ·{" "}{preview.sourceRows.toLocaleString("en")}{" "}source rows. Analysis uses every selected row.</p>}
  </div>;
}
