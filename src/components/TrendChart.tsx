import { useId, useMemo, useState } from "react";
import { motion } from "motion/react";
import { clock, formatValue, scenario } from "../lib/engine";
import type { Point, SignalKey } from "../types";

const COLORS: Record<SignalKey, string> = {
  valve: "#b5ed9a",
  flow: "#b5ed9a",
  temperature: "#e2bc75",
  pressure: "#e9927d",
  separator: "#b4a0db",
  purity: "#8cc7c4",
};

export function TrendChart({
  keys = ["pressure", "temperature", "flow"],
  time = 300,
  points = scenario.points,
  compare,
  large = false,
  intervention,
  onSeek,
}: {
  keys?: SignalKey[];
  time?: number;
  points?: Point[];
  compare?: Point[];
  large?: boolean;
  intervention?: number;
  onSeek?: (time: number) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const id = useId().replaceAll(":", "");
  const width = 700,
    height = large ? 245 : 144,
    left = 42,
    right = 16,
    top = 14,
    bottom = 26;
  const plotWidth = width - left - right,
    plotHeight = height - top - bottom;
  const x = (t: number) => left + (t / 300) * plotWidth;
  const ranges = useMemo(
    () =>
      Object.fromEntries(
        scenario.tags.map((tag) => {
          const values = points
            .map((p) => p[tag.key])
            .concat(compare?.map((p) => p[tag.key]) ?? []);
          const min = Math.min(...values),
            max = Math.max(...values);
          return [
            tag.key,
            { min: min - (max - min) * 0.13, max: max + (max - min) * 0.13 },
          ];
        }),
      ),
    [points, compare],
  );
  const range = (key: SignalKey) => ranges[key];
  const y = (value: number, key: SignalKey) => {
    const r = range(key);
    return top + (1 - (value - r.min) / (r.max - r.min || 1)) * plotHeight;
  };
  const path = (key: SignalKey, data: Point[]) =>
    data
      .filter((p) => p.t <= time)
      .map(
        (p, i) =>
          `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p[key], key).toFixed(1)}`,
      )
      .join(" ");
  const at =
    hover === null
      ? null
      : points[Math.min(Math.round(hover), points.length - 1)];
  return (
    <div className={`trend-chart ${large ? "large" : ""}`}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={
          compare
            ? "Observed and intervention pressure trajectories over five minutes"
            : "Normalized process signal trends over five minutes"
        }
        onPointerMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setHover(
            Math.max(
              0,
              Math.min(
                time,
                ((((event.clientX - rect.left) / rect.width) * width - left) /
                  plotWidth) *
                  300,
              ),
            ),
          );
        }}
        onPointerLeave={() => setHover(null)}
        onClick={() => {
          if (hover !== null) onSeek?.(Math.round(hover));
        }}
      >
        <defs>
          <linearGradient id={`fill-${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#e9927d" stopOpacity=".1" />
            <stop offset="100%" stopColor="#e9927d" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((r) => (
          <g key={r}>
            <line
              className="chart-grid"
              x1={left}
              y1={top + r * plotHeight}
              x2={width - right}
              y2={top + r * plotHeight}
            />
            <text x={left - 10} y={top + r * plotHeight + 3} textAnchor="end">
              {keys.length === 1
                ? Math.round(
                    range(keys[0]).max -
                      r * (range(keys[0]).max - range(keys[0]).min),
                  ).toLocaleString()
                : `${Math.round((1 - r) * 100)}%`}
            </text>
          </g>
        ))}
        {[0, 60, 120, 180, 240, 300].map((t) => (
          <g key={t}>
            <line
              className="chart-grid vertical"
              x1={x(t)}
              y1={top}
              x2={x(t)}
              y2={height - bottom}
            />
            <text x={x(t)} y={height - 7} textAnchor="middle">
              {clock(t)}
            </text>
          </g>
        ))}
        <rect
          x={x(scenario.faultTime)}
          y={top}
          width={Math.max(0, x(time) - x(scenario.faultTime))}
          height={plotHeight}
          fill="#e2bc75"
          opacity=".018"
        />
        <line
          x1={x(scenario.faultTime)}
          y1={top}
          x2={x(scenario.faultTime)}
          y2={height - bottom}
          stroke="#758272"
          strokeDasharray="2 5"
        />
        {keys.length === 1 && keys[0] === "pressure" && (
          <g>
            <line
              x1={left}
              y1={y(3050, "pressure")}
              x2={width - right}
              y2={y(3050, "pressure")}
              stroke="#e9927d"
              strokeOpacity=".5"
              strokeDasharray="3 5"
            />
            <text
              x={width - right - 5}
              y={y(3050, "pressure") - 7}
              textAnchor="end"
              style={{ fill: "#e9927d", fontSize: 8 }}
            >
              TRIP LIMIT / 3,050
            </text>
          </g>
        )}
        {keys.length === 1 && (
          <path
            d={`${path(keys[0], points)} L${x(time)},${height - bottom} L${left},${height - bottom}Z`}
            fill={`url(#fill-${id})`}
          />
        )}
        {keys.map((key) => (
          <path
            key={key}
            d={path(key, points)}
            fill="none"
            stroke={COLORS[key]}
            strokeWidth="1.6"
            strokeLinejoin="round"
          />
        ))}
        {compare && (
          <path
            d={path(keys[0], compare)}
            fill="none"
            stroke="#b5ed9a"
            strokeWidth="2"
          />
        )}
        {intervention !== undefined && (
          <g>
            <line
              x1={x(intervention)}
              y1={top}
              x2={x(intervention)}
              y2={height - bottom}
              stroke="#b5ed9a"
              strokeDasharray="3 4"
            />
            <text
              x={x(intervention) + 7}
              y={top + 9}
              className="intervention-label"
            >
              BYPASS +{intervention}s
            </text>
          </g>
        )}
        <line
          x1={x(time)}
          y1={top}
          x2={x(time)}
          y2={height - bottom}
          stroke="#b5ed9a"
          strokeOpacity=".4"
        />
        {keys.map((key) => (
          <motion.circle
            key={key}
            cx={x(time)}
            cy={y(points[Math.floor(time)][key], key)}
            r="3"
            fill={COLORS[key]}
          />
        ))}
        {at && (
          <g>
            <line
              x1={x(at.t)}
              y1={top}
              x2={x(at.t)}
              y2={height - bottom}
              stroke="#e7eee0"
              strokeDasharray="3 3"
            />
            {keys.map((key) => (
              <circle
                key={key}
                cx={x(at.t)}
                cy={y(at[key], key)}
                r="3.5"
                fill={COLORS[key]}
                stroke="#101512"
                strokeWidth="2"
              />
            ))}
          </g>
        )}
      </svg>
      {at && (
        <div className="chart-tooltip">
          <span>+{clock(at.t)}</span>
          {keys.map((key) => (
            <span key={key} style={{ color: COLORS[key] }}>
              {scenario.tags.find((t) => t.key === key)!.tag}{" "}
              {formatValue(key, at)}
            </span>
          ))}
          {compare && (
            <span className="text-mint">
              BYPASS {Math.round(compare[at.t][keys[0]])}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
