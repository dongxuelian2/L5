import { useMemo, useState } from "react";
import { motion } from "motion/react";
import { detectedAt, formatValue, pointAt, scenario } from "../lib/engine";
import type { SignalKey } from "../types";
import { Panel, StatusDot } from "./Primitives";

const positions: Record<SignalKey, [number, number]> = {
  valve: [54, 79],
  flow: [190, 79],
  temperature: [360, 79],
  pressure: [360, 179],
  separator: [530, 179],
  purity: [530, 79],
};
const signalPaths = [
  "M158 120 H190",
  "M294 120 H360",
  "M412 161 V179",
  "M464 220 H530",
  "M582 179 V161",
];
const orderedSignals: SignalKey[] = [
  "valve",
  "flow",
  "temperature",
  "pressure",
  "separator",
  "purity",
];
const signalRanges = Object.fromEntries(
  scenario.tags.map((tag) => {
    const values = scenario.points.map((point) => point[tag.key]);
    return [tag.key, { min: Math.min(...values), max: Math.max(...values) }];
  }),
);

export function ProcessMap({
  time,
  onSelect,
  selected,
}: {
  time: number;
  onSelect: (key: SignalKey) => void;
  selected: SignalKey | null;
}) {
  const [trace, setTrace] = useState<SignalKey | null>(null);
  const point = pointAt(time);
  const active = time >= scenario.detections.valve.time;
  const traceIndex = trace ? orderedSignals.indexOf(trace) : -1;
  const sample = Math.floor(time);
  const histories = useMemo(
    () =>
      Object.fromEntries(
        scenario.tags.map((tag) => {
          const [x, y] = positions[tag.key];
          const { min, max } = signalRanges[tag.key];
          const start = Math.max(0, sample - 40);
          const d = scenario.points
            .slice(start, sample + 1)
            .map(
              (p, index) =>
                `${index ? "L" : "M"}${x + 9 + ((p.t - start) / 40) * 86},${y + 75 - ((p[tag.key] - min) / (max - min || 1)) * 12}`,
            )
            .join(" ");
          return [tag.key, d];
        }),
      ),
    [sample],
  );
  return (
    <Panel
      code="01"
      title="Process topology"
      className="process-panel"
      action={
        <span className="panel-meta">
          <StatusDot pulse /> 6 signals connected
        </span>
      }
    >
      <div className="map-caption">
        <span>
          <span className="text-mint">──</span> Material flow
        </span>
        <span>
          <span className="text-amber">┄┄</span> Causal propagation
        </span>
        <span className="map-caption-right">Δ DETECTION LAG</span>
      </div>
      <div className={`process-map ${trace ? "is-tracing" : ""}`}>
        <svg
          viewBox="0 0 680 294"
          role="group"
          aria-label="Process topology: cooling valve to flow, reactor temperature and pressure, separator, then product purity"
        >
          <defs>
            <pattern
              id="map-dots"
              width="18"
              height="18"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="1" cy="1" r=".6" fill="#a9bf9c" opacity=".12" />
            </pattern>
            <marker
              id="flow-arrow"
              viewBox="0 0 6 6"
              refX="5"
              refY="3"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M0 0 6 3 0 6" fill="none" stroke="#53664e" />
            </marker>
          </defs>
          <rect width="680" height="294" fill="url(#map-dots)" />
          <path
            d="M25 120 H54 M106 161 V220 H335 M634 120 H655 M634 220 H655"
            className="material-path"
            markerEnd="url(#flow-arrow)"
          />
          <text x="23" y="67" className="map-small">
            COOLING LOOP
          </text>
          <text x="358" y="40" className="map-small">
            REACTION
          </text>
          <text x="528" y="40" className="map-small">
            SEPARATION
          </text>
          <path d="M351 52 H473 V266 H351" className="unit-boundary" />
          <text x="412" y="284" textAnchor="middle" className="map-small">
            R-101 / REACTOR
          </text>
          {signalPaths.map((path, i) => {
            const key = orderedSignals[i + 1];
            const detected = detectedAt(key, time);
            const lag =
              scenario.detections[key].time -
              scenario.detections[orderedSignals[i]].time;
            return (
              <g
                key={path}
                className={`map-edge ${i < traceIndex ? "in-trace" : ""}`}
              >
                <path
                  d={path}
                  className="material-path"
                  markerEnd="url(#flow-arrow)"
                />
                {detected && (
                  <path
                    d={path}
                    className={`signal-path signal-${key} ${i < traceIndex ? "trace-edge" : ""}`}
                  />
                )}
                <text
                  x={
                    i < 2
                      ? i
                        ? 315
                        : 163
                      : i === 3
                        ? 486
                        : i === 2
                          ? 421
                          : 591
                  }
                  y={i < 2 ? 109 : i === 3 ? 208 : 173}
                  className="lag-label"
                >
                  {detected ? `+${lag}s` : "···"}
                </text>
              </g>
            );
          })}
          {scenario.tags.map((tag) => {
            const [x, y] = positions[tag.key];
            const detected = detectedAt(tag.key, time);
            return (
              <g
                key={tag.key}
                className={`process-node node-${tag.color} ${detected ? "detected" : ""} ${selected === tag.key ? "selected" : ""} ${orderedSignals.indexOf(tag.key) <= traceIndex ? "in-trace" : ""} ${detected && time < scenario.detections[tag.key].time + 8 ? "just-detected" : ""}`}
                role="button"
                tabIndex={0}
                aria-label={`Inspect ${tag.name}`}
                onClick={() => onSelect(tag.key)}
                onPointerEnter={() => setTrace(tag.key)}
                onPointerLeave={() => setTrace(null)}
                onFocus={() => setTrace(tag.key)}
                onBlur={() => setTrace(null)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(tag.key);
                  }
                }}
              >
                <rect
                  className="node-bg"
                  x={x}
                  y={y}
                  width="104"
                  height="82"
                  rx="1"
                />
                <path
                  d={`M${x} ${y + 10}V${y}H${x + 10} M${x + 94} ${y}H${x + 104}V${y + 10} M${x} ${y + 72}V${y + 82}H${x + 10} M${x + 94} ${y + 82}H${x + 104}V${y + 72}`}
                  className="node-corners"
                />
                <text x={x + 10} y={y + 18} className="node-tag">
                  {tag.tag}
                </text>
                <circle cx={x + 93} cy={y + 14} r="2" className="node-dot" />
                <text x={x + 10} y={y + 41} className="node-value">
                  {formatValue(tag.key, point)}
                  <tspan className="node-unit" dx="3">
                    {tag.unit}
                  </tspan>
                </text>
                <text x={x + 10} y={y + 56} className="node-name">
                  {tag.key === "temperature"
                    ? "temperature"
                    : tag.key === "separator"
                      ? "separator"
                      : tag.key === "purity"
                        ? "product"
                        : tag.key === "valve"
                          ? "cooling valve"
                          : tag.key === "flow"
                            ? "water flow"
                            : "pressure"}
                </text>
                <path
                  d={`M${x + 9} ${y + 75}H${x + 95}`}
                  className="node-history-baseline"
                />
                <path d={histories[tag.key]} className="node-history" />
              </g>
            );
          })}
          <text x="54" y="253" className="map-small">
            {active ? "╰─ FIRST DEVIATION" : "╰─ BASELINE STABLE"}
          </text>
          {active && (
            <motion.text
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              x="54"
              y="271"
              className="first-deviation"
            >
              CV-101 · +{scenario.detections.valve.time}s
            </motion.text>
          )}
          <text x="23" y="226" className="map-small">
            FEED
          </text>
          <text x="635" y="103" className="map-small">
            OUT
          </text>
        </svg>
      </div>
      <div className="map-bottom">
        <span>
          <span className="text-mint">↳</span>{" "}
          {trace
            ? `TRACE / ${orderedSignals
                .slice(0, traceIndex + 1)
                .map((key) => scenario.tags.find((tag) => tag.key === key)!.tag)
                .join(" → ")}`
            : active
              ? "The first deviation is upstream of the first pressure alarm."
              : "Monitoring baseline. Cooling loop and downstream units are stable."}
        </span>
        <span className="muted">hover to trace · click to inspect ↗</span>
      </div>
    </Panel>
  );
}
