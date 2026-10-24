import { memo, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { cachedSeries } from "./seriesCache";
import { number, timeLabel, type Dataset, type Interval, type TimeAxis } from "./types";

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

export const Plot = memo(function Plot({ times, values, title, axis, threshold, intervals = [], color = "#b5ed9a", domain, thresholdLabel = "threshold" }: {
  times: number[]; values: (number | null)[]; title: string; axis: TimeAxis; threshold?: number; intervals?: Interval[]; color?: string; domain?: [number, number]; thresholdLabel?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (!times.length) return null;
  let low = Infinity, high = -Infinity;
  for (const value of values) if (value != null) { low = Math.min(low, value); high = Math.max(high, value); }
  if (!Number.isFinite(low)) return <div className="ws-notice">{title}: no measured values in this window.</div>;
  if (domain) [low, high] = domain;
  if (threshold !== undefined) { low = Math.min(domain ? low : 0, low, threshold); high = Math.max(high, threshold); }
  const margin = Math.max((high - low) * .08, Math.abs(high) * .002, .001);
  low -= margin; high += margin;
  const first = times[0], last = times[times.length - 1], span = last - first || 1;
  const x = (t: number) => L + (t - first) / span * (W - L - R);
  const y = (v: number) => T + (high - v) / (high - low) * (H - T - B);
  let connected = false;
  const path = plotIndexes(values).map(i => {
    const value = values[i];
    if (value == null) { connected = false; return ""; }
    const point = `${connected ? "L" : "M"}${x(times[i]).toFixed(2)},${y(value).toFixed(2)}`;
    connected = true; return point;
  }).join(" ");
  const active = hover != null && hover < times.length ? hover : null;
  return <figure className="ws-plot">
    <figcaption><span><i style={{ background: color }} />{title}</span><span className="ws-muted">{active == null ? `${times.length.toLocaleString()} displayed points` : `${timeLabel(axis, times[active])} · ${values[active] == null ? "missing" : number(values[active]!)}`}</span></figcaption>
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title} time series${threshold === undefined ? "" : `, threshold ${number(threshold)}`}`}
      onPointerLeave={() => setHover(null)} onPointerMove={e => {
        const rect = e.currentTarget.getBoundingClientRect();
        const t = first + Math.max(0, Math.min(1, ((e.clientX - rect.left) / rect.width * W - L) / (W - L - R))) * span;
        let a = 0, b = times.length - 1;
        while (a < b) { const m = (a + b) >> 1; if (times[m] < t) a = m + 1; else b = m; }
        setHover(a);
      }}>
      <title>{title}{threshold !== undefined ? ` — ${thresholdLabel} ${number(threshold)}` : ""}</title>
      {[0, .5, 1].map(f => <g key={f}><line x1={L} x2={W - R} y1={T + f * (H - T - B)} y2={T + f * (H - T - B)} stroke="#30392d" strokeDasharray="3 5" /><text x={L - 10} y={T + f * (H - T - B) + 4} textAnchor="end">{number(high - f * (high - low))}</text></g>)}
      {intervals.filter(i => i.end >= first && i.start <= last).map((interval, i) => <rect key={i} x={x(Math.max(first, interval.start))} width={Math.max(2, x(Math.min(last, interval.end)) - x(Math.max(first, interval.start)))} y={T} height={H - T - B} fill="#e9927d" opacity=".14" />)}
      {threshold !== undefined && <><line x1={L} x2={W - R} y1={y(threshold)} y2={y(threshold)} stroke="#e2bc75" strokeDasharray="7 4" /><text x={W - R - 4} y={y(threshold) - 5} textAnchor="end" fill="#e2bc75">{thresholdLabel} {number(threshold)}</text></>}
      <path d={path} fill="none" stroke={color} strokeWidth="1.7" vectorEffect="non-scaling-stroke" />
      {active != null && <line x1={x(times[active])} x2={x(times[active])} y1={T} y2={H - B} stroke="#d5dace" opacity=".5" />}
      <text x={L} y={H - 5}>{timeLabel(axis, first)}</text><text x={W - R} y={H - 5} textAnchor="end">{timeLabel(axis, last)}</text>
    </svg>
  </figure>;
});

export function SignalPlots({ dataset, signals, range, intervals }: { dataset: Dataset; signals: string[]; range?: [number, number]; intervals?: Interval[] }) {
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
    return data ? <Plot key={name} times={data.times} values={data.values} title={name} axis={dataset.metadata.time} intervals={intervals} /> :
      <figure className="ws-plot ws-plot-pending" key={name}><figcaption>{name}</figcaption><div className="ws-plot-placeholder">
        {error ? <div role="alert"><p>{error}</p><button type="button" className="ws-outlined" onClick={() => void cache.load([name], true)}>Retry signal</button></div> : <span role="status">Loading {name}…</span>}
      </div></figure>;
  })}
    {preview && <p className="ws-muted">Overview preserves extrema · {preview.sourceRows.toLocaleString()} source rows. Analysis uses every selected row.</p>}
  </div>;
}
