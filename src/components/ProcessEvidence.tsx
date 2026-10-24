import { useState, type ReactNode } from "react";
import { motion } from "motion/react";
import { BlockBar, Count, Panel } from "./Primitives";
import { downloadFile } from "../lib/download";
import metadata from "../lib/processMetadata";
import type { Analysis, Row } from "../lib/platform";
const platform = metadata;
const signalMeta = Object.fromEntries(metadata.signals.map(s => [s.key,s]));
const num = (n: number | null | undefined, digits=1) => n == null ? "—" : n.toFixed(digits);
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

export function EvidenceResult({ pending, children, pendingLabel = "Updating evidence for the selected window…" }: { pending: boolean; children: ReactNode; pendingLabel?: string }) {
  return <div className="runtime-evidence-result" aria-busy={pending}>
    <div className="runtime-evidence-content" style={{ visibility: pending ? "hidden" : undefined }} aria-hidden={pending || undefined} inert={pending}>{children}</div>
    {pending && <p className="runtime-evidence-updating" role="status">{pendingLabel}</p>}
  </div>;
}

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
  incident: { rows: Row[] };
  analysis: Analysis | null;
  time: number;
  selected: string;
  onSelect: (s: string) => void;
}) {
  const row = incident.rows.filter(r => r.t <= time).at(-1)!;
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
            const active = analysis?.diagnosis.paths.some(
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
            const detection = analysis?.diagnosis.detections[key],
              bad = Boolean(analysis && !analysis.diagnosis.health[key]?.usable);
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
                  {num(row?.[key], key === "composition" ? 2 : 1)}
                  <tspan className="p-node-unit"> {signalMeta[key].unit}</tspan>
                </text>
                <text x="10" y="56" className="p-node-sub">
                  {!analysis ? "EVIDENCE UPDATING" : bad
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

export function EvidenceView({
  incident,
  analysis,
  time, hypothesis, onHypothesis, updating = false,
}: {
  incident: { rows: Row[] };
  analysis: Analysis;
  time: number;
  hypothesis: string;
  onHypothesis: (id: string) => void;
  updating?: boolean;
}) {
  const d = analysis.diagnosis;
  const [selected, setSelected] = useState("valve");
  const candidateId = hypothesis || d.candidates[0].id;
  const candidate = d.candidates.find((c) => c.id === candidateId) || d.candidates[0];
  const health = d.health[selected];
  return (
    <>
      <div className="p-evidence-grid">
        <Topology
          incident={incident}
          analysis={updating ? null : analysis}
          time={time}
          selected={selected}
          onSelect={setSelected}
        />
        <Panel
          title="Competing hypotheses"
          code="02"
          action={<span className="p-tag">12 CANDIDATES</span>}
        >
          <EvidenceResult pending={updating}>
            <div className="p-candidates">
              {d.candidates.map((c, i) => (
                <button
                  className={c.id === candidateId ? "active" : ""}
                  key={c.id}
                  onClick={() => onHypothesis(c.id)}
                  aria-pressed={c.id === candidateId}
                >
                  <span className="p-rank">{String(i + 1).padStart(2, "0")}</span>
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
              <details><summary>Observed paths involving this hypothesis</summary>{d.paths.filter(path=>candidate.parts.some(p=>p.signal===path.source||p.signal===path.target)).map((path,i)=><p key={i}>{signalMeta[path.source].tag} → {signalMeta[path.target].tag} · lag {path.lag}s · correlation {path.correlation} · {path.trusted ? "usable" : "unreliable evidence"}</p>)}</details>
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
          </EvidenceResult>
        </Panel>
      </div>
      <div className="p-controls-grid">
        <Panel
          title="Controller evidence"
          code="03"
          action={<span className="p-tag">SP / PV / OP / FEEDBACK</span>}
        >
          <EvidenceResult pending={updating}>
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
          </EvidenceResult>
        </Panel>
        <Panel
          title="Signal evidence"
          code="04"
          action={
            <span
              className={`p-tag ${!updating && health?.usable ? "text-mint" : "text-amber"}`}
            >
              {updating ? "UPDATING" : health?.status.toUpperCase()}
            </span>
          }
        >
          <div className="p-signal-readout">
            <div>
              <span>{signalMeta[selected].tag}</span>
              <b>
                {num(incident.rows.filter(r => r.t <= time).at(-1)?.[selected])}
                <small>{signalMeta[selected].unit}</small>
              </b>
            </div>
            <MiniPlot
              rows={incident.rows.filter(r => r.t <= time)}
              signal={selected}
              width={220}
              height={70}
            />
          </div>
          <EvidenceResult pending={updating}>
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
          </EvidenceResult>
        </Panel>
      </div>
      <div className="p-triple">
        <Panel title="Next best observation" code="05" tone="violet">
          <EvidenceResult pending={updating}>
            <div className="p-next">
              <div className="p-subtitle">DISCRIMINATOR PRIORITY · HEURISTIC</div>
              {d.nextMeasurements.map((m, i) => (
                <div key={m.signal}>
                  <span className="text-violet">{String(i + 1).padStart(2, "0")}</span>
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
          </EvidenceResult>
        </Panel>
        <Panel title="Procedure alignment" code="06">
          <EvidenceResult pending={updating}>
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
          </EvidenceResult>
        </Panel>
        <Panel title="Evidence health" code="07">
          <EvidenceResult pending={updating}>
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
                ? `regular ${d.clock.step ?? 1}s cadence`
                : `${d.clock.gaps} gaps detected`}{" "}
              · sustained deviation confirmed over 3 seconds.
            </div>
          </EvidenceResult>
        </Panel>
      </div>
    </>
  );
}

export function AlarmView({ analysis }: { analysis: Analysis }) {
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

export function TraceView({ analysis }: { analysis: Analysis }) {
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
            Tools can be invoked from the investigation controls.
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
