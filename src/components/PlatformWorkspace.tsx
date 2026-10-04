import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { BlockBar, Count, Panel, ScrambleText } from "./Primitives";
import { downloadFile } from "../lib/engine";
import {
  csvFor,
  exportDossier,
  num,
  platform,
  readMemory,
  signalMeta,
  type Action,
  type Analysis,
  type Incident,
  type Row,
  type SavedIncident,
} from "../lib/platform";
import "./platform.css";

const POS: Record<string, [number, number]> = {
  utility: [80, 47],
  pump: [80, 160],
  cooling_op: [260, 47],
  valve: [260, 160],
  flow: [440, 160],
  temperature: [620, 160],
  pressure: [800, 160],
  separator: [800, 280],
  purity: [620, 280],
  feed_op: [80, 280],
  feed_valve: [260, 280],
  feed: [440, 280],
  composition: [440, 47],
};
const EDGE_COLOR: Record<string, string> = {
  material: "#b5ed9a",
  energy: "#e2bc75",
  control: "#b4a0db",
  feedback: "#71858e",
};

function MiniPlot({
  rows,
  signal,
  width = 120,
  height = 25,
}: {
  rows: Row[];
  signal: string;
  width?: number;
  height?: number;
}) {
  const data = rows.map((r) => r[signal]).filter((v): v is number => v != null);
  if (!data.length) return null;
  const low = Math.min(...data),
    high = Math.max(...data),
    span = Math.max(signalMeta[signal]?.scale || 0.01, high - low);
  const path = data
    .map(
      (v, i) =>
        `${i ? "L" : "M"}${(i / Math.max(1, data.length - 1)) * width},${height - 2 - ((v - low) / span) * (height - 4)}`,
    )
    .join(" ");
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
    >
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

function Topology({
  incident,
  analysis,
  time,
  selected,
  onSelect,
}: {
  incident: Incident;
  analysis: Analysis;
  time: number;
  selected: string;
  onSelect: (s: string) => void;
}) {
  const row = incident.rows[Math.min(time, incident.rows.length - 1)];
  return (
    <Panel
      title="Process & control topology"
      code="01"
      className="p-topology"
      action={<span className="p-tag">14 typed paths</span>}
    >
      <div className="p-map-scroll">
        <svg
          className="p-map"
          viewBox="0 0 900 344"
          role="group"
          aria-label="Branching process and controller evidence graph"
        >
          <defs>
            <pattern
              id="p-grid"
              width="18"
              height="18"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="1" cy="1" r=".6" fill="#35412e" />
            </pattern>
          </defs>
          <rect width="900" height="344" fill="url(#p-grid)" opacity=".48" />
          {platform.edges.map((edge, i) => {
            const [x, y] = POS[edge.source],
              [x2, y2] = POS[edge.target];
            const feedback = edge.kind === "feedback";
            const path = feedback
              ? `M${x - 40},${y - 30} Q${(x + x2) / 2},${y - 104} ${x2 + 40},${y2 + 30}`
              : `M${x},${y} L${x2},${y2}`;
            const active = analysis.diagnosis.paths.some(
              (p) =>
                p.source === edge.source &&
                p.target === edge.target &&
                p.trusted,
            );
            return (
              <g
                key={i}
                className={active ? "p-edge active" : "p-edge"}
                style={{ color: EDGE_COLOR[edge.kind] }}
              >
                <path
                  d={path}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={active ? 1.5 : 1}
                  strokeDasharray={feedback ? "4 5" : undefined}
                />
                {active && (
                  <path
                    className="p-flow-dash"
                    d={path}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    strokeDasharray="2 36"
                  />
                )}
              </g>
            );
          })}
          {Object.entries(POS).map(([key, [x, y]]) => {
            const detection = analysis.diagnosis.detections[key],
              bad = !analysis.diagnosis.health[key]?.usable;
            return (
              <g
                key={key}
                className={`p-node ${selected === key ? "selected" : ""} ${detection ? "deviated" : ""} ${bad ? "untrusted" : ""}`}
                transform={`translate(${x - 65},${y - 33})`}
                role="button"
                tabIndex={0}
                aria-label={`Inspect ${signalMeta[key].tag}`}
                onClick={() => onSelect(key)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(key);
                  }
                }}
              >
                <rect width="130" height="66" rx="2" />
                <path
                  d="M0,12 V0 H12 M118,0 H130 V12 M130,54 V66 H118 M12,66 H0 V54"
                  className="p-corners"
                />
                <text x="10" y="17" className="p-node-tag">
                  {signalMeta[key].tag}
                </text>
                <text x="120" y="17" textAnchor="end" className="p-node-dot">
                  {bad ? "!" : detection ? "◆" : "·"}
                </text>
                <text x="10" y="40" className="p-node-value">
                  {num(row[key], key === "composition" ? 2 : 1)}
                  <tspan className="p-node-unit"> {signalMeta[key].unit}</tspan>
                </text>
                <text x="10" y="56" className="p-node-sub">
                  {bad
                    ? "EVIDENCE CHECK"
                    : detection
                      ? `ONSET +${detection.onset}s`
                      : "WITHIN BASELINE"}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="p-map-legend">
        {Object.entries(EDGE_COLOR).map(([name, color]) => (
          <span key={name}>
            <i style={{ background: color }} />
            {name}
          </span>
        ))}
        <span className="p-push">◆ observed deviation</span>
      </div>
    </Panel>
  );
}

function RecoveryLab({ incident }: { incident: Incident }) {
  const recovery = incident.recovery;
  const [actionId, setActionId] = useState("bypass");
  const [start, setStart] = useState(90);
  const action = recovery.actions.find((a) => a.id === actionId)!;
  const trial = action.trials.find((t) => t.time === start)!;
  const xs = (t: number) => 48 + ((t - 20) / 220) * 752;
  const peaks = [...action.trials.map((t) => t.peak), recovery.threshold];
  const low = Math.floor((Math.min(...peaks) - 30) / 50) * 50,
    high = Math.ceil((Math.max(...peaks) + 30) / 50) * 50;
  const ys = (v: number) => 204 - ((v - low) / (high - low)) * 165;
  const curve = action.trials
    .map((t, i) => `${i ? "L" : "M"}${xs(t.time)},${ys(t.peak)}`)
    .join(" ");
  function badge(a: Action) {
    return [
      recovery.safest === a.id ? "Largest margin" : null,
      recovery.lowestLoss === a.id ? "Lowest loss" : null,
      recovery.latest === a.id ? "Latest recovery" : null,
    ]
      .filter(Boolean)
      .join(" · ");
  }
  return (
    <div className="p-recovery">
      <div className="p-recovery-intro">
        <span className="p-large-glyph">⑂</span>
        <div>
          <div className="eyebrow text-mint">PHYSICS VERIFIES</div>
          <h2>
            Find the last recoverable second<span className="text-mint">.</span>
          </h2>
          <p>
            {recovery.evaluated.toLocaleString()} branches · 7 actions ·
            exhaustive 1-second search · +240s horizon
          </p>
        </div>
        <div className="p-formula">
          t* = max {"{"} t : P<sub>peak</sub>(t) &lt; 3,050 {"}"}
        </div>
      </div>
      <div className="p-recovery-grid">
        <Panel
          title="Intervention search"
          code="01"
          action={<span className="p-tag">SIMULATED</span>}
        >
          <div className="p-actions">
            {recovery.actions.map((a) => (
              <button
                key={a.id}
                onClick={() => setActionId(a.id)}
                className={a.id === actionId ? "active" : ""}
                aria-pressed={a.id === actionId}
              >
                <span className="p-action-glyph">
                  {a.latest == null ? "×" : "⑂"}
                </span>
                <span>
                  <strong>{a.name}</strong>
                  <small>
                    {badge(a) ||
                      `Severity ${a.severity}/5 · utility weight ${a.cost}`}
                  </small>
                </span>
                <b className={a.latest == null ? "text-coral" : "text-mint"}>
                  {a.latest == null ? "—" : `+${a.latest}s`}
                </b>
              </button>
            ))}
          </div>
          <div className="p-panel-note">
            Rankings compare each action at its own latest safe start. Loss =
            integrated feed deficit; quality = mean purity deficit.
          </div>
        </Panel>
        <Panel
          title="Recovery envelope"
          code="02"
          action={
            <span
              className={`p-tag ${trial.safe ? "text-mint" : "text-coral"}`}
            >
              {trial.safe ? "WITHIN THRESHOLD" : "THRESHOLD CROSSED"}
            </span>
          }
        >
          <div className="p-envelope-title">
            <div>
              <strong>{action.name}</strong>
              <p>
                {recovery.base.trip === null
                  ? "No physical trip predicted in this horizon."
                  : `Unmitigated model crosses the threshold at +${recovery.base.trip}s.`}
              </p>
            </div>
            <div>
              <b className="text-mint">
                {action.latest == null ? "—" : `+${action.latest}s`}
              </b>
              <small>
                {recovery.base.trip === null
                  ? "horizon limit"
                  : "last recoverable start"}
              </small>
            </div>
          </div>
          <svg
            viewBox="0 0 830 246"
            className="p-envelope"
            role="img"
            aria-label="Maximum pressure versus intervention start time"
          >
            {[0, 1, 2, 3].map((i) => {
              const v = low + ((high - low) * i) / 3;
              return (
                <g key={i}>
                  <line
                    x1="48"
                    x2="800"
                    y1={ys(v)}
                    y2={ys(v)}
                    stroke="#30392d"
                  />
                  <text x="40" y={ys(v) + 4} textAnchor="end">
                    {Math.round(v)}
                  </text>
                </g>
              );
            })}
            {action.intervals.map(([a, b]) => (
              <rect
                key={a}
                x={xs(a)}
                y="25"
                width={Math.max(1, xs(b) - xs(a))}
                height="179"
                fill="#b5ed9a"
                opacity=".04"
              />
            ))}
            <line
              x1="48"
              x2="800"
              y1={ys(3050)}
              y2={ys(3050)}
              stroke="#e9927d"
              strokeDasharray="5 5"
            />
            <text x="792" y={ys(3050) - 7} textAnchor="end" fill="#e9927d">
              TRIP 3,050 kPa
            </text>
            <motion.path
              key={action.id}
              d={curve}
              fill="none"
              stroke="#b5ed9a"
              strokeWidth="2"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.65 }}
            />
            <line
              x1={xs(start)}
              x2={xs(start)}
              y1="25"
              y2="204"
              stroke="#84907f"
              strokeDasharray="2 4"
            />
            <circle
              cx={xs(start)}
              cy={ys(trial.peak)}
              r="5"
              fill={trial.safe ? "#b5ed9a" : "#e9927d"}
            />
            {[20, 60, 100, 140, 180, 220, 240].map((t) => (
              <text key={t} x={xs(t)} y="226" textAnchor="middle">
                +{t}s
              </text>
            ))}
          </svg>
          <label className="p-range-label" htmlFor="intervention-time">
            Intervention start <strong>+{start}s</strong>
          </label>
          <input
            id="intervention-time"
            className="p-range"
            type="range"
            min={20}
            max={240}
            step={1}
            value={start}
            onChange={(e) => setStart(+e.target.value)}
          />
          <div className="p-trial-stats">
            <div>
              <span>PRESSURE PEAK</span>
              <b>
                {num(trial.peak, 0)} <small>kPa</small>
              </b>
            </div>
            <div>
              <span>THRESHOLD MARGIN</span>
              <b className={trial.safe ? "text-mint" : "text-coral"}>
                {num(3050 - trial.peak, 0)} <small>kPa</small>
              </b>
            </div>
            <div>
              <span>PRODUCTION LOSS</span>
              <b>
                {num(trial.productionLoss)}
                <small>%</small>
              </b>
            </div>
            <div>
              <span>QUALITY LOSS</span>
              <b>
                {num(trial.qualityLoss, 2)} <small>pp</small>
              </b>
            </div>
          </div>
        </Panel>
      </div>
      <div className="p-method-strip">
        <span className="text-violet">⌗ MODEL CONDITION</span>
        <span>
          Fitted hypothesis: {platform.faults[incident.fit.hypothesis]} ·
          normalized RMSE {incident.fit.error}
        </span>
        <span>
          Safe means no physical pressure crossing within 240s. It is
          conditional model evidence.
        </span>
      </div>
    </div>
  );
}

function EvidenceView({
  incident,
  analysis,
  time,
}: {
  incident: Incident;
  analysis: Analysis;
  time: number;
}) {
  const d = analysis.diagnosis;
  const [selected, setSelected] = useState("valve");
  const [candidateId, setCandidateId] = useState(d.candidates[0].id);
  useEffect(() => setCandidateId(d.candidates[0].id), [d]);
  const candidate = d.candidates.find((c) => c.id === candidateId)!;
  const health = d.health[selected];
  return (
    <>
      <div className="p-evidence-grid">
        <Topology
          incident={incident}
          analysis={analysis}
          time={time}
          selected={selected}
          onSelect={setSelected}
        />
        <Panel
          title="Competing hypotheses"
          code="02"
          action={<span className="p-tag">12 CANDIDATES</span>}
        >
          <div className="p-candidates">
            {d.candidates.slice(0, 4).map((c, i) => (
              <button
                className={c.id === candidateId ? "active" : ""}
                key={c.id}
                onClick={() => setCandidateId(c.id)}
                aria-pressed={c.id === candidateId}
              >
                <span className="p-rank">0{i + 1}</span>
                <span className="p-candidate-name">
                  <strong>{c.name}</strong>
                  <BlockBar
                    value={c.score / 100}
                    count={22}
                    color={i === 0 ? "mint" : "amber"}
                  />
                </span>
                <span className="p-score">
                  {c.score}
                  <small>/ 100</small>
                </span>
              </button>
            ))}
          </div>
          <div className="p-score-note">
            Evidence support ≠ calibrated probability
          </div>
          <div className="p-candidate-detail" key={candidate.id}>
            <div className="p-subtitle">
              <span>{candidate.confidence.toUpperCase()} SUPPORT</span>
              <span>topology +{candidate.topology}</span>
            </div>
            {candidate.support.map((s) => (
              <p key={s}>
                <span className="text-mint">+</span>
                {s}
              </p>
            ))}
            {candidate.against.map((s) => (
              <p key={s}>
                <span className="text-coral">−</span>
                {s}
              </p>
            ))}
            {candidate.unresolved.map((s) => (
              <p key={s}>
                <span className="text-amber">?</span>
                {s}
              </p>
            ))}
            <details className="p-score-detail">
              <summary>Inspect score components ＋</summary>
              {candidate.parts.map((p) => (
                <div key={p.signal}>
                  <span>{signalMeta[p.signal].tag}</span>
                  <span>weight {p.weight}</span>
                  <b
                    className={p.contribution >= 0 ? "text-mint" : "text-coral"}
                  >
                    {p.contribution >= 0 ? "+" : ""}
                    {p.contribution}
                  </b>
                </div>
              ))}
              <small>
                Sum of signed evidence + topology; clipped to 0–100.
              </small>
            </details>
          </div>
        </Panel>
      </div>
      <div className="p-controls-grid">
        <Panel
          title="Controller evidence"
          code="03"
          action={<span className="p-tag">SP / PV / OP / FEEDBACK</span>}
        >
          <div className="p-controllers">
            {d.controllers.map((c) => (
              <div className="p-controller" key={c.id}>
                <div className="p-controller-top">
                  <strong>{c.id}</strong>
                  <span
                    className={
                      c.mismatch != null && Math.abs(c.mismatch) > 12
                        ? "text-amber"
                        : "text-mint"
                    }
                  >
                    {c.mismatch == null
                      ? "EVIDENCE MISSING"
                      : Math.abs(c.mismatch) > 12
                        ? "ACTUATOR MISMATCH"
                        : "TRACKING"}
                  </span>
                </div>
                <div className="p-controller-values">
                  {[
                    ["SP", c.sp],
                    ["PV", c.pv],
                    ["OP", c.op],
                    ["FB", c.feedback],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <span>{label}</span>
                      <b>{num(value as number | null)}</b>
                    </div>
                  ))}
                </div>
                <div className="p-controller-footer">
                  <span>Output ceiling {num(c.limit, 0)}%</span>
                  <span>
                    Demand − feedback <strong>{num(c.mismatch)}%</strong>
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
        <Panel
          title="Signal evidence"
          code="04"
          action={
            <span
              className={`p-tag ${health?.usable ? "text-mint" : "text-amber"}`}
            >
              {health?.status.toUpperCase()}
            </span>
          }
        >
          <div className="p-signal-readout">
            <div>
              <span>{signalMeta[selected].tag}</span>
              <b>
                {num(incident.rows[time][selected])}
                <small>{signalMeta[selected].unit}</small>
              </b>
            </div>
            <MiniPlot
              rows={incident.rows.slice(0, time + 1)}
              signal={selected}
              width={220}
              height={70}
            />
          </div>
          <div className="p-signal-facts">
            <p>
              First confirmed deviation{" "}
              <strong>
                {d.detections[selected]
                  ? `+${d.detections[selected].time}s`
                  : "none"}
              </strong>
            </p>
            <p>
              Baseline-relative change{" "}
              <strong>{num(d.changes[selected])}</strong>
            </p>
            <p>
              Freshness{" "}
              <strong>
                {health?.freshness == null ? "missing" : `${health.freshness}s`}
              </strong>
            </p>
          </div>
          <div className="p-panel-note">
            {health?.detail}.{" "}
            {health?.usable
              ? "Available to the evidence scorer."
              : "Excluded from strong process-causality evidence."}
          </div>
        </Panel>
      </div>
      <div className="p-triple">
        <Panel title="Next best observation" code="05" tone="violet">
          <div className="p-next">
            <div className="p-subtitle">DISCRIMINATOR PRIORITY · HEURISTIC</div>
            {d.nextMeasurements.map((m, i) => (
              <div key={m.signal}>
                <span className="text-violet">0{i + 1}</span>
                <div>
                  <strong>{m.tag}</strong>
                  <p>{m.reason}</p>
                </div>
                <b>{m.value}</b>
              </div>
            ))}
            <p className="p-panel-note">
              Distinguishes{" "}
              {d.candidates
                .slice(0, 2)
                .map((c) => c.name)
                .join(" / ")}
              . Scores are uncalibrated inspection priorities.
            </p>
          </div>
        </Panel>
        <Panel title="Procedure alignment" code="06">
          <div className="p-sop">
            <div className="p-subtitle">
              {analysis.sop.id} · REV {analysis.sop.revision}
            </div>
            <h3>{analysis.sop.title}</h3>
            {analysis.sop.preconditions.map((p) => (
              <p key={p.name}>
                <span className={p.satisfied ? "text-mint" : "text-coral"}>
                  {p.satisfied ? "[✓]" : "[×]"}
                </span>
                {p.name}
              </p>
            ))}
            <div
              className={`p-procedure-status ${analysis.sop.applicable ? "text-mint" : "text-amber"}`}
            >
              {analysis.sop.applicable
                ? "PRECONDITIONS SATISFIED"
                : "PRECONDITIONS NOT SATISFIED"}
            </div>
            <small>{analysis.sop.status}</small>
          </div>
        </Panel>
        <Panel title="Evidence health" code="07">
          <div className="p-health-summary">
            <b>
              <Count
                value={Object.values(d.health).filter((h) => h.usable).length}
              />
              <small>/18</small>
            </b>
            <span>
              channels available
              <br />
              for causal evidence
            </span>
          </div>
          <div className="p-health-grid">
            {platform.signals.map((s) => (
              <button
                key={s.key}
                title={`${s.tag}: ${d.health[s.key]?.status}`}
                onClick={() => setSelected(s.key)}
                className={d.health[s.key]?.usable ? "healthy" : "degraded"}
              >
                <span>{s.tag}</span>
                <i>{d.health[s.key]?.usable ? "·" : "!"}</i>
              </button>
            ))}
          </div>
          <div className="p-panel-note">
            Clock:{" "}
            {d.clock.regular
              ? "regular 1s cadence"
              : `${d.clock.gaps} gaps detected`}{" "}
            · four-sample deviation confirmation.
          </div>
        </Panel>
      </div>
    </>
  );
}

function AlarmView({ analysis }: { analysis: Analysis }) {
  const a = analysis.alarms;
  const [filter, setFilter] = useState("all");
  const events = a.events.filter((e) => filter === "all" || e.kind === filter);
  const bins = Array.from(
    { length: 24 },
    (_, i) =>
      a.events.filter((e) => e.t >= i * 10 && e.t < (i + 1) * 10).length,
  );
  const max = Math.max(1, ...bins);
  return (
    <div className="p-alarm-layout">
      <Panel
        title="Flood compression"
        code="01"
        action={<span className="p-tag">10 EVENTS / 30s</span>}
      >
        <div className="p-alarm-funnel">
          <div>
            <b>{a.eventCount}</b>
            <span>journal events</span>
          </div>
          <i>→</i>
          <div>
            <b>{a.uniqueConditions}</b>
            <span>unique conditions</span>
          </div>
          <i>→</i>
          <div>
            <b>{a.clusters.length}</b>
            <span>process clusters</span>
          </div>
        </div>
        <div className="p-alarm-histogram">
          {bins.map((n, i) => (
            <div key={i} title={`+${i * 10}…${i * 10 + 9}s: ${n} events`}>
              <motion.i
                initial={{ height: 0 }}
                animate={{ height: `${(n / max) * 100}%` }}
                transition={{ duration: 0.4, delay: i * 0.012 }}
              />
              <span>{i % 4 === 0 ? `+${i * 10}` : ""}</span>
            </div>
          ))}
        </div>
        <div className="p-panel-note">
          {a.floods.length
            ? a.floods.map((f) => `Flood +${f.start}–${f.end}s`).join(" · ")
            : "No flood segment detected."}{" "}
          · {a.reannunciations} repeated annunciations retained in the journal.
        </div>
        <div className="p-condition-list">
          {a.conditions.map((c) => (
            <div key={c.id}>
              <span className="text-amber">{c.id}</span>
              <span>{c.classification}</span>
              <span>{c.activations} onset(s)</span>
              <b>{c.events}</b>
              <span className={c.actionable ? "text-mint" : "text-muted"}>
                {c.actionable ? "REVIEW ACTION" : "CONSEQUENTIAL"}
              </span>
            </div>
          ))}
        </div>
      </Panel>
      <Panel
        title="Raw alarm journal"
        code="02"
        action={
          <button
            className="subtle-button"
            onClick={() =>
              downloadFile(
                "triplens-alarm-journal.json",
                JSON.stringify(a, null, 2),
                "application/json",
              )
            }
          >
            Export ↓
          </button>
        }
      >
        <div className="p-alarm-filters">
          {["all", "activation", "reannunciation", "return"].map((f) => (
            <button
              key={f}
              aria-pressed={filter === f}
              className={filter === f ? "active" : ""}
              onClick={() => setFilter(f)}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="p-alarm-journal">
          {events.length ? (
            events.map((e, i) => (
              <div key={`${e.t}-${e.condition}-${i}`}>
                <time>+{e.t}s</time>
                <strong>{e.condition}</strong>
                <span
                  className={
                    e.kind === "activation"
                      ? "text-amber"
                      : e.kind === "return"
                        ? "text-mint"
                        : "text-muted"
                  }
                >
                  {e.kind}
                </span>
                <span>{e.chain}</span>
              </div>
            ))
          ) : (
            <div className="p-empty">No matching events in this window.</div>
          )}
        </div>
      </Panel>
    </div>
  );
}

function TraceView({ analysis }: { analysis: Analysis }) {
  return (
    <div className="p-trace-layout">
      <div className="p-trace-intro">
        <div className="eyebrow text-mint">INVESTIGATION AUDIT</div>
        <h2>
          Every conclusion.
          <br />
          An inspectable trail.
        </h2>
        <p>
          Observe → compare → challenge → verify. Each record contains the exact
          inputs and computed output of the investigation policy.
        </p>
        <div className="p-policy">
          <span className="text-violet">●</span> Local deterministic policy
          <br />
          <span className="text-muted">
            Structured model interface reserved.
          </span>
        </div>
      </div>
      <div className="p-trace-list">
        {analysis.trace.map((step, i) => (
          <motion.details
            key={step.tool}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.035 }}
          >
            <summary>
              <span className="p-trace-index">
                {String(step.index).padStart(2, "0")}
              </span>
              <span>
                <strong>{step.tool}</strong>
                <small>{JSON.stringify(step.args)}</small>
              </span>
              <span className="text-mint">✓</span>
              <span className="text-muted">＋</span>
            </summary>
            <div className="p-trace-result">
              <span className="eyebrow text-muted">COMPUTED OUTPUT</span>
              <pre>{JSON.stringify(step.result, null, 2)}</pre>
            </div>
          </motion.details>
        ))}
      </div>
    </div>
  );
}

function LearnView({
  incident,
  onSelect,
  saved,
  onMemoryChange,
}: {
  incident: Incident;
  onSelect: (id: string) => void;
  saved: SavedIncident[];
  onMemoryChange: () => void;
}) {
  const b = platform.benchmark;
  const [imported, setImported] = useState<Analysis | null>(null),
    [importError, setImportError] = useState(""),
    [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  async function importCSV(file: File) {
    setImported(null);
    setImportError("");
    setBusy(true);
    try {
      if (file.size > 2_000_000)
        throw new Error("CSV must be smaller than 2 MB.");
      const response = await fetch("/api/replay", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csv: await file.text() }),
      });
      if (!response.headers.get("content-type")?.includes("application/json"))
        throw new Error(
          "CSV analysis needs the Python service. Run python3 server.py and open http://127.0.0.1:8787.",
        );
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Unable to analyze CSV.");
      setImported(data);
    } catch (e) {
      setImportError(e instanceof Error ? e.message : "CSV analysis failed.");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }
  return (
    <>
      <div className="p-learn-top">
        <Panel
          title="Incident memory"
          code="01"
          action={
            <span className="p-tag">{saved.length} SAVED / THIS BROWSER</span>
          }
        >
          <div className="p-memory-list">
            {saved.length ? (
              saved.map((s) => (
                <button key={s.id} onClick={() => onSelect(s.id)}>
                  <span className="text-mint">▣</span>
                  <span>
                    <strong>
                      {s.id} · {s.hypothesis}
                    </strong>
                    <small>
                      {s.note || "Evidence dossier retained for review"} ·{" "}
                      {new Date(s.savedAt).toLocaleDateString()}
                    </small>
                  </span>
                  <b>{s.score}</b>
                  <span>↗</span>
                </button>
              ))
            ) : (
              <div className="p-empty">
                <span>▣</span>
                <h3>Keep the evidence, carry it forward.</h3>
                <p>
                  Save a completed investigation to retain its fingerprint and
                  operator note across visits.
                </p>
                <button
                  className="subtle-button bordered"
                  onClick={() => onSelect(incident.id)}
                >
                  Open investigation ↗
                </button>
              </div>
            )}
          </div>
          {saved.length > 0 && (
            <div className="p-memory-actions">
              <button
                className="subtle-button"
                onClick={() =>
                  downloadFile(
                    "triplens-memory.json",
                    JSON.stringify(saved, null, 2),
                    "application/json",
                  )
                }
              >
                Export memory ↓
              </button>
              <button
                className="subtle-button"
                onClick={() => {
                  localStorage.removeItem("triplens-memory-v2");
                  onMemoryChange();
                }}
              >
                Clear saved memory
              </button>
            </div>
          )}
        </Panel>
        <Panel title="Similar process fingerprints" code="02">
          <div className="p-similar">
            {incident.similar.map((s) => (
              <button key={s.id} onClick={() => onSelect(s.id)}>
                <div>
                  <span>{s.id}</span>
                  <strong>
                    {s.similarity}
                    <small>/100</small>
                  </strong>
                </div>
                <h3>{s.leading}</h3>
                <p>
                  Shared direction:{" "}
                  {s.shared.slice(0, 5).join(" · ") || "No matching deviations"}
                </p>
                <BlockBar value={s.similarity / 100} count={20} />
              </button>
            ))}
          </div>
          <div className="p-panel-note">
            Distance over observed channel changes; similarity is not a
            confirmed common root cause.
          </div>
        </Panel>
      </div>
      <Panel
        title="Verification matrix"
        code="03"
        action={<span className="p-tag">INTERNAL REGRESSION</span>}
      >
        <div className="p-bench-stats">
          <div>
            <b>{b.scenarioCount}</b>
            <span>parameter variants</span>
          </div>
          <div>
            <b>{b.faultCoverage}</b>
            <span>fault families</span>
          </div>
          <div>
            <b>
              {num(b.top1 * 100, 0)}
              <small>%</small>
            </b>
            <span>top-1 support ranking</span>
          </div>
          <div>
            <b>
              {num(b.top3 * 100, 0)}
              <small>%</small>
            </b>
            <span>top-3 coverage</span>
          </div>
          <div>
            <b>
              {b.medianDelay}
              <small>s</small>
            </b>
            <span>median detection delay</span>
          </div>
          <div>
            <b>
              {b.falsePositiveRuns}
              <small>/{b.healthyRuns}</small>
            </b>
            <span>healthy runs flagged</span>
          </div>
        </div>
        <div className="p-benchmark-grid">
          {Object.entries(platform.faults).map(([id, label]) => (
            <div key={id}>
              <span>{label}</span>
              <div>
                {b.records
                  .filter((r) => r.fault === id)
                  .map((r) => (
                    <span
                      key={r.variant}
                      className={r.top1 ? "passed" : "failed"}
                      title={`Variant ${r.variant + 1}: ${platform.faults[r.predicted]}, delay ${r.delay}s`}
                    >
                      {r.top1 ? "✓" : "×"}
                    </span>
                  ))}
              </div>
            </div>
          ))}
        </div>
        <div className="p-panel-note">
          {b.limitation} Variants alter severity, start, delay, noise,
          controller response and operating point.
        </div>
      </Panel>
      <div className="p-learn-bottom">
        <Panel
          title="Alarm rationalization"
          code="04"
          action={<span className="p-tag">{incident.id}</span>}
        >
          <div className="p-rationalization">
            {incident.alarms.rationalization.length ? (
              incident.alarms.rationalization.map((r) => (
                <div key={r.condition}>
                  <div>
                    <strong>{r.condition}</strong>
                    <span className="text-amber">{r.repeats} repeats</span>
                  </div>
                  <p>{r.recommendation}</p>
                  <span className="p-tag">{r.kind}</span>
                </div>
              ))
            ) : (
              <div className="p-empty">
                <p>No repeat-annunciation candidates in this session.</p>
              </div>
            )}
          </div>
        </Panel>
        <Panel title="Historian CSV replay" code="05">
          <div className="p-import">
            <div className="p-import-glyph">⇡</div>
            <h3>Bring a signal window.</h3>
            <p>
              Time-ordered samples, 20 stable baseline rows, the same blind
              evidence pipeline. Missing channels remain unresolved.
            </p>
            <div className="p-import-buttons">
              <button
                className="primary-button"
                disabled={busy}
                onClick={() => input.current?.click()}
              >
                {busy ? "Analyzing…" : "Import CSV ↑"}
              </button>
              <button
                className="subtle-button bordered"
                onClick={() =>
                  downloadFile(
                    "triplens-signal-window.csv",
                    csvFor(incident),
                    "text/csv",
                  )
                }
              >
                Download example ↓
              </button>
            </div>
            <input
              ref={input}
              type="file"
              accept=".csv,text/csv"
              hidden
              aria-label="Historian CSV file"
              onChange={(e) => {
                if (e.target.files?.[0]) void importCSV(e.target.files[0]);
              }}
            />
            {importError && (
              <p role="alert" className="text-coral">
                {importError}
              </p>
            )}
            {imported && (
              <div className="p-import-result" role="status">
                <span className="text-mint">✓ WINDOW ANALYZED</span>
                <h3>{imported.diagnosis.candidates[0].name}</h3>
                <p>
                  {imported.diagnosis.status} ·{" "}
                  {imported.diagnosis.candidates[0].score}/100 support ·{" "}
                  {imported.alarms.eventCount} alarm events
                </p>
                <p>
                  {
                    Object.values(imported.diagnosis.health).filter(
                      (h) => h.usable,
                    ).length
                  }
                  /18 usable channels
                </p>
                <button
                  className="subtle-button"
                  onClick={() =>
                    downloadFile(
                      "triplens-import-analysis.json",
                      JSON.stringify(imported, null, 2),
                      "application/json",
                    )
                  }
                >
                  Export computed evidence ↓
                </button>
              </div>
            )}
            <div className="p-panel-note">
              Python service required for imports. Data is processed by the
              local service; no external model request.
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}

export function PlatformWorkspace({
  mode,
  onModeChange,
}: {
  mode: "investigate" | "learn";
  onModeChange: (mode: "investigate" | "learn") => void;
}) {
  const [incidentId, setIncidentId] = useState(platform.cases[0].id),
    [tab, setTab] = useState<"evidence" | "recovery" | "trace" | "alarms">(
      "evidence",
    ),
    [time, setTime] = useState(240);
  const [saved, setSaved] = useState(readMemory),
    [note, setNote] = useState(""),
    [notice, setNotice] = useState("");
  const incident = platform.cases.find((c) => c.id === incidentId)!;
  const analysis: Analysis =
    time === 240 ? incident : incident.snapshots.find((s) => s.time === time)!;
  const d = analysis.diagnosis,
    a = analysis.alarms;
  useEffect(() => {
    setTime(240);
    setTab("evidence");
    setNote("");
    setNotice("");
  }, [incidentId]);
  useEffect(() => {
    if (time !== 240 && tab === "recovery") setTab("evidence");
  }, [time, tab]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 3500);
    return () => clearTimeout(timer);
  }, [notice]);
  function select(id: string) {
    setIncidentId(id);
    onModeChange("investigate");
  }
  function save() {
    try {
      const item: SavedIncident = {
        id: incident.id,
        hypothesis: d.candidates[0].name,
        score: d.candidates[0].score,
        events: a.eventCount,
        savedAt: new Date().toISOString(),
        note,
        fingerprint: d.changes,
      };
      const next = [item, ...saved.filter((s) => s.id !== item.id)];
      localStorage.setItem("triplens-memory-v2", JSON.stringify(next));
      setSaved(next);
      setNotice("Incident fingerprint and note saved.");
    } catch {
      setNotice(
        "Browser storage unavailable. Export the dossier to retain it.",
      );
    }
  }
  return (
    <div className="platform-workspace">
      <div className="view-heading p-heading">
        <div>
          <div className="eyebrow">
            <span className="text-mint">◆</span>{" "}
            {mode === "learn"
              ? "POST-INCIDENT INTELLIGENCE"
              : "MULTI-EVIDENCE INVESTIGATION"}{" "}
            <span className="heading-separator">/</span> PROCESS 02
          </div>
          <h1>
            <ScrambleText
              text={
                mode === "learn"
                  ? "Every incident makes the next one clearer."
                  : "Follow the evidence. Change the outcome."
              }
            />
          </h1>
          <p>
            {mode === "learn"
              ? "Retain fingerprints. Challenge assumptions. Improve the alarm system."
              : "Detect → compress → investigate → verify → intervene → learn"}
          </p>
        </div>
        <span className="p-version">
          ENGINE / 02
          <br />
          <b>18 CHANNELS</b>
        </span>
      </div>
      <div className="p-sessionbar">
        <label>
          INCIDENT SESSION
          <select
            aria-label="Incident session"
            value={incidentId}
            onChange={(e) => setIncidentId(e.target.value)}
          >
            {platform.cases.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id} / {c.title}
              </option>
            ))}
          </select>
        </label>
        <span className="p-session-note">
          Diagnosis receives observed signals only
        </span>
        <div className="p-export-actions">
          <button
            onClick={() =>
              exportDossier(incident, analysis, time, "md", note ? [note] : [])
            }
          >
            RCA .md ↓
          </button>
          <button
            onClick={() =>
              exportDossier(
                incident,
                analysis,
                time,
                "json",
                note ? [note] : [],
              )
            }
          >
            JSON ↓
          </button>
        </div>
      </div>
      {mode === "learn" ? (
        <LearnView
          incident={incident}
          onSelect={select}
          saved={saved}
          onMemoryChange={() => setSaved(readMemory())}
        />
      ) : (
        <>
          <div className="p-metrics">
            <div>
              <span>ALARM EVENTS → CONDITIONS → CLUSTERS</span>
              <div className="p-compression">
                <b>
                  <Count value={a.eventCount} />
                </b>
                <i>→</i>
                <b>{a.uniqueConditions}</b>
                <i>→</i>
                <b className="text-mint">{a.clusters.length}</b>
                <span>{a.reannunciations} repeats</span>
              </div>
            </div>
            <div>
              <span>LEADING HYPOTHESIS</span>
              <strong>
                {d.status === "nominal"
                  ? "No confirmed deviation"
                  : d.candidates[0].name}
              </strong>
              <small className="text-mint">
                {d.candidates[0].confidence} support · {d.candidates[0].score}
                /100 evidence
              </small>
            </div>
            <div>
              <span>FIRST CONFIRMED DEVIATION</span>
              <b>
                {d.firstDetection == null ? "—" : `+${d.firstDetection}`}
                <small>s</small>
              </b>
              <small>
                {a.firstAlarm == null
                  ? "No operator alarm"
                  : `First alarm +${a.firstAlarm}s · ${a.floods.length} flood segment(s)`}
              </small>
            </div>
          </div>
          <div className="p-workflowbar">
            <div
              className="p-tabs"
              role="tablist"
              aria-label="Investigation workspace"
            >
              {(
                [
                  ["evidence", "⌘", "Evidence"],
                  ["recovery", "⑂", "Interventions"],
                  ["trace", "≡", "Tool audit"],
                  ["alarms", "≋", "Alarm journal"],
                ] as const
              ).map(([id, icon, label]) => (
                <button
                  key={id}
                  role="tab"
                  aria-selected={tab === id}
                  disabled={id === "recovery" && time !== 240}
                  onClick={() => setTab(id)}
                  className={tab === id ? "active" : ""}
                >
                  {icon} {label}
                  {tab === id && <motion.i layoutId="p-tab" />}
                </button>
              ))}
            </div>
            <div className="p-asof">
              <span>AS OF</span>
              {[40, 70, 110, 180, 240].map((t) => (
                <button
                  key={t}
                  aria-pressed={time === t}
                  className={time === t ? "active" : ""}
                  onClick={() => setTime(t)}
                >
                  +{t}s
                </button>
              ))}
            </div>
          </div>
          {time !== 240 && (
            <div className="p-prefix-notice">
              Evidence is recomputed using only samples through +{time}s.
              Recovery fitting is available after the complete window.
            </div>
          )}
          <AnimatePresence mode="wait">
            <motion.div
              key={`${incidentId}-${tab}`}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              {tab === "evidence" ? (
                <EvidenceView
                  incident={incident}
                  analysis={analysis}
                  time={time}
                />
              ) : tab === "recovery" ? (
                <RecoveryLab incident={incident} />
              ) : tab === "alarms" ? (
                <AlarmView analysis={analysis} />
              ) : (
                <TraceView analysis={analysis} />
              )}
            </motion.div>
          </AnimatePresence>
          <div className="p-closeout">
            <span className="text-mint">▣</span>
            <div>
              <strong>Carry this investigation forward</strong>
              <p>Retain the observed fingerprint and your review note.</p>
            </div>
            <input
              aria-label="Operator review note"
              placeholder="Add an operator or maintenance note…"
              value={note}
              maxLength={500}
              onChange={(e) => setNote(e.target.value)}
            />
            <button
              className="primary-button"
              onClick={save}
              disabled={time !== 240}
            >
              Save to memory ↗
            </button>
          </div>
        </>
      )}
      <div className="p-footnote">
        <span>TRIPLENS / COUPLED PROCESS MODEL</span>
        <span>Evidence before inference. Decisions before actuation.</span>
      </div>
      <AnimatePresence>
        {notice && (
          <motion.div
            className="toast"
            role="status"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
          >
            {notice}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
