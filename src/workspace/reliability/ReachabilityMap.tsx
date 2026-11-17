import { useId } from "react";
import { t } from "../../lib/text";
import type { Analysis, Box, Pair, Replay } from "./reachabilityTypes";

export type View = "reach" | "nominal" | "viability" | "nominalViability" | "viableTarget";
export const label = (key: string) => t("reach." + key);
export const fmt = (value: number | null) => value == null ? "—" : value.toLocaleString("en", { maximumFractionDigits: 3 });
export const pair = (a: Pair) => a.map(fmt).join(" / ");
export const command = ([pump, valve]: Pair) => fmt(pump) + "% / " + fmt(valve);

const colors: Record<string, string> = { target: "#d0b66e", recoverable: "#8ac6a4", nonrecoverable: "#987281",
  unsafe: "#383d47", viable: "#75b7cb", nonviable: "#987281", trajectory: "#fff7e2" };

export function mapIndex(data: Analysis, heads: Pair) {
  const { axes, spacing } = data.numerical;
  const indices = heads.map((value, i) => Math.max(0, Math.min(axes[i].length - 1, Math.floor(value / spacing[i] + .5))));
  return { indices, cell: indices[0] * axes[1].length + indices[1] };
}

export function StateMap({ data, heads, previous, view, select, replay }: {
  data: Analysis; heads: Pair; previous: number; view: View; select: (head: Pair) => void; replay?: Replay;
}) {
  const id = useId();
  const { axes, spacing } = data.numerical;
  const nx = axes[0].length, ny = axes[1].length, maxX = axes[0][nx - 1], maxY = axes[1][ny - 1];
  const w = 540, h = 430, left = 58, top = 20, right = 520, bottom = 376;
  const x = (value: number) => left + value / maxX * (right - left);
  const y = (value: number) => bottom - value / maxY * (bottom - top);
  const ranks = view === "nominal" ? data.nominalRanks : view === "viableTarget" ? data.viableTargetRanks : data.ranks;
  const viable = view === "nominalViability" ? data.nominalViable : data.viable;
  const isViability = view === "viability" || view === "nominalViability";
  const layers: Record<string, string[]> = {};
  const boundaries: string[] = [];
  for (let i = 0; i < nx; i++) {
    for (let j = 0; j < ny; j++) {
      const index = i * ny + j;
      const kind = !data.safe[index] ? "unsafe" : isViability ? viable[index][previous] ? "viable" : "nonviable"
        : ranks[index][previous] === 0 ? "target" : ranks[index][previous] > 0 ? "recoverable" : "nonrecoverable";
      const x0 = x(axes[0][i] - spacing[0] / 2), y0 = y(axes[1][j] + spacing[1] / 2);
      const dx = spacing[0] / maxX * (right - left), dy = spacing[1] / maxY * (bottom - top);
      const rect = "M" + x0.toFixed(3) + "," + y0.toFixed(3) + "h" + dx.toFixed(3) + "v" + dy.toFixed(3) + "h-" + dx.toFixed(3) + "Z";
      (layers[kind] ??= []).push(rect);
      if (data.boundary[index][previous]) boundaries.push(rect);
    }
  }
  const legend = isViability ? ["viable", "nonviable", "unsafe"] : ["target", "recoverable", "nonrecoverable", "unsafe"];
  const outline = (box: Box, color: string, dash?: string) => <rect x={x(box[0][0])} y={y(box[1][1])}
    width={x(box[0][1]) - x(box[0][0])} height={y(box[1][0]) - y(box[1][1])} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray={dash} />;
  const trajectory = replay?.trajectory.map(p => x(p.level1).toFixed(2) + "," + y(p.level2).toFixed(2)).join(" ");
  return <figure className="reach-map">
    <svg viewBox={`0 0 ${w} ${h}`} tabIndex={0} role="img" aria-label={label("map")} aria-describedby={id + "-hint"}
      onClick={e => {
        const rect = e.currentTarget.getBoundingClientRect();
        const px = (e.clientX - rect.left) * w / rect.width, py = (e.clientY - rect.top) * h / rect.height;
        if (px >= left && px <= right && py >= top && py <= bottom)
          select([axes[0][Math.round((px - left) / (right - left) * (nx - 1))], axes[1][Math.round((bottom - py) / (bottom - top) * (ny - 1))]]);
      }}
      onKeyDown={e => {
        const arrows: Record<string, Pair> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
        const delta = arrows[e.key];
        if (!delta) return;
        e.preventDefault();
        const { indices } = mapIndex(data, heads.every(Number.isFinite) ? heads : [0, 0]);
        select([axes[0][Math.max(0, Math.min(nx - 1, indices[0] + delta[0]))], axes[1][Math.max(0, Math.min(ny - 1, indices[1] + delta[1]))]]);
      }}>
      <defs>
        <clipPath id={id + "-clip"}><rect x={left} y={top} width={right - left} height={bottom - top} /></clipPath>
        <pattern id={id + "-hatch"} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(38)">
          <line x1="0" x2="0" y1="0" y2="6" stroke="#151b21" opacity=".6" strokeWidth="2" />
        </pattern>
      </defs>
      <g clipPath={`url(#${id}-clip)`}>
        {Object.entries(layers).map(([kind, segments]) => <path key={kind} fill={colors[kind]} d={segments.join("")} />)}
        <path fill={`url(#${id}-hatch)`} d={boundaries.join("")} />
        {outline(data.config.safe, "#eff6f1", "5 3")}
        {outline(data.config.target, "#f1d994")}
        {trajectory && <polyline points={trajectory} fill="none" stroke={colors.trajectory} strokeWidth={2.4} />}
        {Number.isFinite(heads[0] + heads[1]) && <circle cx={x(heads[0])} cy={y(heads[1])} r={5} fill="#131c19" stroke={colors.trajectory} strokeWidth={2} />}
      </g>
      {[0, .25, .5, .75, 1].map(f => <g key={f}>
        <text x={x(f * maxX)} y={bottom + 19} textAnchor="middle">{fmt(f * maxX)}</text>
        <text x={left - 9} y={y(f * maxY) + 4} textAnchor="end">{fmt(f * maxY)}</text>
      </g>)}
      <text x={(left + right) / 2} y={h - 10} textAnchor="middle">{label("level1")}</text>
      <text transform={`rotate(-90 18 ${(top + bottom) / 2})`} x={18} y={(top + bottom) / 2} textAnchor="middle">{label("level2")}</text>
    </svg>
    <figcaption>
      <div className="reach-legend">{[...legend, ...(trajectory ? ["trajectory"] : [])].map(kind =>
        <span key={kind}><i style={{ background: colors[kind] }} />{label(kind)}</span>)}
        <span><i className="reach-hatch" />{label("boundary")}</span></div>
      <p className="ws-muted" id={id + "-hint"}>{label("mapHint")}</p>
    </figcaption>
  </figure>;
}
