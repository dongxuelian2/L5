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
  "M145 113 H190",
  "M281 113 H360",
  "M405 146 V179",
  "M451 213 H530",
  "M576 179 V146",
];

export function ProcessMap({
  time,
  onSelect,
  selected,
}: {
  time: number;
  onSelect: (key: SignalKey) => void;
  selected: SignalKey | null;
}) {
  const point = pointAt(time);
  const active = time >= scenario.detections.valve.time;
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
        <span className="map-caption-right">UNIT / 01</span>
      </div>
      <div className="process-map">
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
            d="M25 114 H54 M99 147 V213 H335 M622 113 H655 M622 213 H655"
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
          <path d="M351 52 H460 V258 H351" className="unit-boundary" />
          <text x="405" y="274" textAnchor="middle" className="map-small">
            R-101 / REACTOR
          </text>
          {signalPaths.map((path, i) => {
            const key = (
              [
                "flow",
                "temperature",
                "pressure",
                "separator",
                "purity",
              ] as SignalKey[]
            )[i];
            const detected = detectedAt(key, time);
            return (
              <g key={path}>
                <path
                  d={path}
                  className="material-path"
                  markerEnd="url(#flow-arrow)"
                />
                {detected && (
                  <path d={path} className={`signal-path signal-${key}`} />
                )}
                <text
                  x={
                    i < 2
                      ? i
                        ? 305
                        : 160
                      : i === 3
                        ? 477
                        : i === 2
                          ? 416
                          : 590
                  }
                  y={i < 2 ? 103 : i === 3 ? 201 : 166}
                  className="lag-label"
                >
                  {detected ? `+${scenario.detections[key].time}s` : "···"}
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
                className={`process-node node-${tag.color} ${detected ? "detected" : ""} ${selected === tag.key ? "selected" : ""}`}
                role="button"
                tabIndex={0}
                aria-label={`Inspect ${tag.name}`}
                onClick={() => onSelect(tag.key)}
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
                  width="92"
                  height="68"
                  rx="1"
                />
                <path
                  d={`M${x} ${y + 10}V${y}H${x + 10} M${x + 82} ${y}H${x + 92}V${y + 10} M${x} ${y + 58}V${y + 68}H${x + 10} M${x + 82} ${y + 68}H${x + 92}V${y + 58}`}
                  className="node-corners"
                />
                <text x={x + 10} y={y + 18} className="node-tag">
                  {tag.tag}
                </text>
                <circle cx={x + 81} cy={y + 14} r="2" className="node-dot" />
                <text x={x + 10} y={y + 41} className="node-value">
                  {formatValue(tag.key, point)}
                  <tspan className="node-unit" dx="3">
                    {tag.unit}
                  </tspan>
                </text>
                <text x={x + 10} y={y + 57} className="node-name">
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
          {active
            ? "The first deviation is upstream of the first pressure alarm."
            : "Monitoring baseline. Cooling loop and downstream units are stable."}
        </span>
        <span className="muted">click a node to inspect ↗</span>
      </div>
    </Panel>
  );
}
