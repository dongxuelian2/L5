import { AnimatePresence, motion } from "motion/react";
import { scenario } from "../lib/engine";
import type { IncidentBrief } from "../types";
import { BlockBar, Glyph, Panel, ScrambleText, StatusDot } from "./Primitives";

export function RootCauses({
  ready,
  selected,
  onSelect,
  onInspect,
}: {
  ready: boolean;
  selected: string;
  onSelect: (id: string) => void;
  onInspect: () => void;
}) {
  const candidate = scenario.candidates.find((c) => c.id === selected)!;
  return (
    <Panel
      code="02"
      title="Root-cause ranking"
      className="root-panel"
      action={<span className="panel-meta">evidence score / 100</span>}
    >
      <div className="ranking-list">
        {scenario.candidates.map((c, index) => (
          <button
            key={c.id}
            className={`candidate ${selected === c.id ? "active" : ""}`}
            onClick={() => onSelect(c.id)}
          >
            <span className="candidate-index">0{index + 1}</span>
            <div className="candidate-body">
              <span className="candidate-name">{c.name}</span>
              <span className="candidate-meta">
                {c.tag} <span>·</span> {ready ? c.status : "Awaiting evidence"}
              </span>
              <BlockBar
                value={ready ? c.score / 100 : 0}
                color={index === 0 ? "mint" : index === 1 ? "amber" : "violet"}
                count={25}
              />
            </div>
            <span
              className={`candidate-score ${index === 0 ? "text-mint" : ""}`}
            >
              {ready ? c.score : "—"}
              <span>↗</span>
            </span>
          </button>
        ))}
      </div>
      <AnimatePresence mode="wait">
        <motion.div
          key={selected + String(ready)}
          className="candidate-evidence"
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.16 }}
        >
          <div className="eyebrow">
            <span className="text-mint">└─</span>{" "}
            {ready ? "WHY THIS RANKS HERE" : "LISTENING TO THE PROCESS"}
          </div>
          <p>
            {ready
              ? candidate.support
              : "Baseline signals are stable. Ranking begins after the propagation path becomes observable."}
          </p>
          <button className="text-button" onClick={onInspect} disabled={!ready}>
            Inspect evidence <Glyph>↗</Glyph>
          </button>
        </motion.div>
      </AnimatePresence>
    </Panel>
  );
}

export function AnalystPanel({
  brief,
  step,
  running,
  error,
  onRun,
  onExport,
  onCompare,
  ready,
}: {
  brief: IncidentBrief | null;
  step: number;
  running: boolean;
  error: string | null;
  onRun: () => void;
  onExport: () => void;
  onCompare: () => void;
  ready: boolean;
}) {
  const complete = !!brief && !running;
  return (
    <Panel
      code="04"
      title="Incident analyst"
      className="analyst-panel"
      action={
        <span className="panel-meta">
          <StatusDot tone={running ? "amber" : "mint"} pulse={running} />{" "}
          {running ? "investigating" : complete ? "brief ready" : "ready"}
        </span>
      }
    >
      <div className="analyst-content">
        <div className="analyst-prompt">
          <span className="text-mint">❯</span>
          <span>{scenario.analyst.prompt}</span>
          <span className="prompt-return">↵</span>
        </div>
        {!brief && !running && (
          <div className="analyst-idle">
            <div className="analyst-sigil" aria-hidden="true">
              ┌─┐
              <br />
              ├╳┤
              <br />
              └─┘
            </div>
            <div>
              <p>
                Follow the evidence.
                <br />
                <span className="muted">
                  Connect the signals to the source.
                </span>
              </p>
              <button className="text-button" onClick={onRun} disabled={!ready}>
                Investigate incident <Glyph>↗</Glyph>
              </button>
              {!ready && (
                <span className="hint">Waiting for downstream signals</span>
              )}
            </div>
          </div>
        )}
        {running && (
          <div className="analyst-steps" aria-live="polite">
            {(brief?.steps ?? scenario.analyst.steps).map((item, i) => (
              <div
                key={item.tool}
                className={`analyst-step ${i === step ? "current" : i < step ? "done" : "waiting"}`}
              >
                <span>{i < step ? "✓" : i === step ? "◈" : "·"}</span>
                <span>
                  {i === step ? (
                    <ScrambleText text={item.action} />
                  ) : (
                    item.action
                  )}
                </span>
                <span className="step-tool">
                  {i < step ? "done" : i === step ? "running" : "queued"}
                </span>
              </div>
            ))}
          </div>
        )}
        {complete && (
          <motion.div
            className="analyst-result"
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="eyebrow text-mint">✓ EVIDENCE CONNECTED</div>
            <p>{brief.summary}</p>
            <div className="analyst-actions">
              <button className="text-button" onClick={onCompare}>
                Test an intervention ↗
              </button>
              <button className="subtle-button" onClick={onExport}>
                Export brief ↓
              </button>
            </div>
          </motion.div>
        )}
        {error && (
          <div className="error-message" role="alert">
            {error}
            <button onClick={onRun} className="text-button">
              Retry ↻
            </button>
          </div>
        )}
      </div>
      <div className="analyst-bottom">
        <span>
          <span className="text-violet">◇</span>{" "}
          {complete
            ? `${brief.steps.length} evidence steps · structured brief`
            : "Signals → topology → evidence → conclusion"}
        </span>
        <span className="cursor-block" aria-hidden="true">
          ▊
        </span>
      </div>
    </Panel>
  );
}
