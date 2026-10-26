import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
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
  useLocale();
  const candidate = scenario.candidates.find((c) => c.id === selected)!;
  return (
    <Panel
      code="02"
      title={tr("Root-cause ranking")}
      className="root-panel"
      action={<span className="panel-meta">{tr("evidence score / 100")}</span>}
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
              <span className="candidate-name">{tr(c.name)}</span>
              <span className="candidate-meta">
                {c.tag} <span>·</span> {ready ? tr(c.status) : tr("Awaiting evidence")}
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
            {ready ? tr("WHY THIS RANKS HERE") : tr("LISTENING TO THE PROCESS")}
          </div>
          <p>
            {ready
              ? tr(candidate.support)
              : tr("Baseline signals are stable. Ranking begins after the propagation path becomes observable.")}
          </p>
          <button className="text-button" onClick={onInspect} disabled={!ready}>
            {" "}{tr("Inspect evidence")}{" "}<Glyph>↗</Glyph>
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
  useLocale();
  const complete = !!brief && !running;
  return (
    <Panel
      code="04"
      title={tr("Incident analyst")}
      className="analyst-panel"
      action={
        <span className="panel-meta">
          <StatusDot tone={running ? "amber" : "mint"} pulse={running} />{" "}
          {running ? tr("investigating") : complete ? tr("brief ready") : tr("ready")}
        </span>
      }
    >
      <div className="analyst-content">
        <div className="analyst-prompt">
          <span className="text-mint">❯</span>
          <span>{tr(scenario.analyst.prompt)}</span>
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
                {" "}{tr("Follow the evidence.")}{" "}<br />
                <span className="muted">
                  {" "}{tr("Connect the signals to the source.")}{" "}</span>
              </p>
              <button className="text-button" onClick={onRun} disabled={!ready}>
                {" "}{tr("Investigate incident")}{" "}<Glyph>↗</Glyph>
              </button>
              {!ready && (
                <span className="hint">{tr("Waiting for downstream signals")}</span>
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
                    <ScrambleText text={!brief || brief.provider === "local" ? tr(item.action) : item.action} />
                  ) : (
                    !brief || brief.provider === "local" ? tr(item.action) : item.action
                  )}
                </span>
                <span className="step-tool">
                  {i < step ? tr("done") : i === step ? tr("running") : tr("queued")}
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
            <div className="eyebrow text-mint">{tr("✓ EVIDENCE CONNECTED")}</div>
            <p>{brief.provider === "local" ? tr(brief.summary) : brief.summary}</p>
            <details className="analyst-evidence-trail">
              <summary>
                <span>{tr("Read the evidence trail")}</span>
                <span>
                  {brief.steps.length}{" "}{tr("checks")}{" "}<span aria-hidden="true">+</span>
                </span>
              </summary>
              <div>
                {brief.steps.map((item, i) => (
                  <div className="trail-step" key={item.tool}>
                    <span className="trail-step-index">0{i + 1}</span>
                    <div>
                      <strong>{brief.provider === "local" ? tr(item.action) : item.action}</strong>
                      <p>{brief.provider === "local" ? tr(item.result) : item.result}</p>
                    </div>
                  </div>
                ))}
                <div className="trail-limit">
                  <span className="text-amber">◇</span>
                  <p>{brief.provider === "local" ? tr(brief.limitation) : brief.limitation}</p>
                </div>
              </div>
            </details>
            <div className="analyst-actions">
              <button className="text-button" onClick={onCompare}>
                {" "}{tr("Test an intervention ↗")}{" "}</button>
              <button className="subtle-button" onClick={onExport}>
                {" "}{tr("Export brief ↓")}{" "}</button>
            </div>
          </motion.div>
        )}
        {error && (
          <div className="error-message" role="alert">
            {errorMessage(error)}
            <button onClick={onRun} className="text-button">
              {" "}{tr("Retry ↻")}{" "}</button>
          </div>
        )}
      </div>
      <div className="analyst-bottom">
        <span>
          <span className="text-violet">◇</span>{" "}
          {complete
            ? tr("{0} evidence steps · structured brief", {0: brief.steps.length})
            : tr("Signals → topology → evidence → conclusion")}
        </span>
        <span className="cursor-block" aria-hidden="true">
          ▊
        </span>
      </div>
    </Panel>
  );
}
