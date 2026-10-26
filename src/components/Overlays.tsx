import { t as tr, useLocale } from "../i18n";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { motion } from "motion/react";
import {
  alarmsAt,
  clock,
  downloadFile,
  formatValue,
  pointAt,
  scenario,
  wallClock,
} from "../lib/engine";
import type { SignalKey } from "../types";
import { BlockBar, Glyph, StatusDot } from "./Primitives";
import { TrendChart } from "./TrendChart";

export function Modal({
  title,
  eyebrow,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  eyebrow: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useLocale();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    function key(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab") {
        const focusable = ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), select, textarea, [tabindex="0"]',
        );
        if (!focusable?.length) return;
        const first = focusable[0],
          last = focusable[focusable.length - 1];
        if (
          event.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === ref.current)
        ) {
          event.preventDefault();
          last.focus();
        } else if (
          !event.shiftKey &&
          (document.activeElement === last ||
            document.activeElement === ref.current)
        ) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", key);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, [onClose]);
  return (
    <motion.div
      className="modal-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <motion.div
        ref={ref}
        tabIndex={-1}
        className={`modal ${wide ? "modal-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        initial={{ opacity: 0, y: 18, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 12 }}
        transition={{ duration: 0.24 }}
      >
        <div className="modal-header">
          <div>
            <span className="eyebrow text-mint">{eyebrow}</span>
            <h2>{title}</h2>
          </div>
          <button
            className="close-button"
            aria-label={tr("Close dialog")}
            onClick={onClose}
          >
            × <kbd>ESC</kbd>
          </button>
        </div>
        {children}
      </motion.div>
    </motion.div>
  );
}

export function SignalInspector({
  signal,
  time,
  onClose,
}: {
  signal: SignalKey;
  time: number;
  onClose: () => void;
}) {
  useLocale();
  const tag = scenario.tags.find((t) => t.key === signal)!;
  const point = pointAt(time),
    detection = scenario.detections[signal];
  const available = time >= detection.time;
  return (
    <Modal
      title={tr(tag.name)}
      eyebrow={tr("SIGNAL INSPECTOR / {0}", {0: tag.tag})}
      onClose={onClose}
    >
      <div className="signal-value">
        <span className={`text-${tag.color}`}>
          {formatValue(signal, point)}
          <small>{tag.unit}</small>
        </span>
        <span className="signal-state">
          <StatusDot tone={available ? "amber" : "mint"} />
          {available ? tr("DEVIATION DETECTED") : tr("WITHIN BASELINE")}
        </span>
      </div>
      <TrendChart keys={[signal]} time={time} large />
      <div className="inspect-stats">
        <div>
          <span>{tr("Baseline")}</span>
          <strong>
            {tag.baseline} {tag.unit}
          </strong>
        </div>
        <div>
          <span>{tr("First detection")}</span>
          <strong>{available ? `+${clock(detection.time)}` : tr("Pending")}</strong>
        </div>
        <div>
          <span>{tr("Robust deviation")}</span>
          <strong>{available ? `${detection.z} σ` : "—"}</strong>
        </div>
      </div>
      <div className="evidence-note">
        <span className="text-mint">└─</span>
        <p>
          {" "}{tr("Detection requires four consecutive readings beyond 6× the robust baseline scale (median / MAD). Values above show deviation at the first confirmed detection.")}{" "}</p>
      </div>
      <div className="modal-footer">
        <span>{wallClock(time)}{" "}{tr("· 1 s sampling")}</span>
        <button
          className="subtle-button"
          onClick={() =>
            downloadFile(
              `${tag.tag}.json`,
              JSON.stringify(
                {
                  tag,
                  detection: available ? detection : null,
                  samples: scenario.points
                    .filter((p) => p.t <= time)
                    .map((p) => ({ t: p.t, value: p[signal] })),
                },
                null,
                2,
              ),
            )
          }
        >
          {" "}{tr("Export signal ↓")}{" "}</button>
      </div>
    </Modal>
  );
}

export function EvidenceInspector({
  candidateId,
  onClose,
}: {
  candidateId: string;
  onClose: () => void;
}) {
  useLocale();
  const candidate = scenario.candidates.find((c) => c.id === candidateId)!;
  return (
    <Modal
      title={tr(candidate.name)}
      eyebrow={tr("EVIDENCE / {0}", {0: candidate.tag})}
      onClose={onClose}
    >
      <div className="evidence-score">
        <span className="text-mint">
          {candidate.score}
          <small>/100</small>
        </span>
        <div>
          <span className="eyebrow">{tr("EVIDENCE SUPPORT")}</span>
          <BlockBar value={candidate.score / 100} count={28} />
        </div>
      </div>
      <div className="evidence-section">
        <h3 className="text-mint">{tr("[+] Supporting observations")}</h3>
        <p>{tr(candidate.support)}</p>
      </div>
      <div className="evidence-section">
        <h3 className="text-amber">{tr("[−] Counter-evidence & uncertainty")}</h3>
        <p>{tr(candidate.against)}</p>
      </div>
      <div className="evidence-path">
        {scenario.tags.slice(0, 4).map((tag, i) => (
          <div key={tag.key}>
            <span className="text-mint">
              {i === 0 ? "┌" : i === 3 ? "└" : "├"}─
            </span>
            <span>{tag.tag}</span>
            <span>{tr(tag.name)}</span>
            <span className="muted">+{scenario.detections[tag.key].time}s</span>
          </div>
        ))}
      </div>
      <div className="modal-footer">
        <span>{tr("Evidence score ≠ calibrated probability")}</span>
        <span className="text-mint">{tr("TRACEABLE / 01")}</span>
      </div>
    </Modal>
  );
}

export function AlarmInspector({
  time,
  chainId,
  onClose,
}: {
  time: number;
  chainId: string | null;
  onClose: () => void;
}) {
  useLocale();
  const [filter, setFilter] = useState(chainId ?? "all");
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("all");
  const events = alarmsAt(time).filter(
    (e) =>
      (filter === "all" || e.chain === filter) &&
      (severity === "all" || e.severity.length === 2) &&
      `${e.tag} ${e.message} ${e.severity}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <Modal
      title={tr("Behind every alarm.")}
      eyebrow={tr("ALARM JOURNAL / {0}", {0: scenario.id})}
      onClose={onClose}
      wide
    >
      <div className="alarm-filters">
        <div className="filter-tabs">
          {[{ id: "all", name: tr("All events") }, ...scenario.chains].map((c) => (
            <button
              key={c.id}
              className={filter === c.id ? "selected" : ""}
              onClick={() => setFilter(c.id)}
            >
              {tr(c.name)}
            </button>
          ))}
        </div>
        <div className="alarm-search">
          <input
            aria-label={tr("Search alarms")}
            placeholder={tr("/ search tag or message")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button
            className={severity === "critical" ? "selected" : ""}
            onClick={() =>
              setSeverity((s) => (s === "all" ? "critical" : "all"))
            }
          >
            HH / LL
          </button>
        </div>
      </div>
      <div className="alarm-table-wrap">
        <table className="alarm-table">
          <thead>
            <tr>
              <th>{tr("TIME")}</th>
              <th>{tr("TAG")}</th>
              <th>{tr("LEVEL")}</th>
              <th>{tr("MESSAGE")}</th>
              <th>{tr("VALUE")}</th>
            </tr>
          </thead>
          <tbody>
            {[...events].reverse().map((event) => (
              <tr key={event.id}>
                <td>{wallClock(event.t)}</td>
                <td>{event.tag}</td>
                <td>
                  <span
                    className={
                      event.severity.length === 2 ? "alarm-high" : "alarm-low"
                    }
                  >
                    {event.severity}
                  </span>
                </td>
                <td>
                  {tr(event.message)}
                  {event.repeat && (
                    <span className="repeat-mark" title={tr("Repeated annunciation")}>
                      {" "}
                      ↻
                    </span>
                  )}
                </td>
                <td>{event.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!events.length && (
          <div className="empty-state">{tr("No events match this view.")}</div>
        )}
      </div>
      <div className="modal-footer">
        <span>
          {events.length}{" "}{tr("events · observed through +")}{clock(time)}
        </span>
        <button
          className="subtle-button"
          onClick={() =>
            downloadFile(
              "triplens-alarms.json",
              JSON.stringify(events, null, 2),
            )
          }
        >
          {" "}{tr("Export journal ↓")}{" "}</button>
      </div>
    </Modal>
  );
}

export function Counterfactual({ onClose }: { onClose: () => void }) {
  useLocale();
  const [selected, setSelected] = useState(90);
  const [run, setRun] = useState(90);
  const [running, setRunning] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const branch = scenario.branches.find((b) => b.time === run)!;
  const peak = Math.round(Math.max(...scenario.points.map((p) => p.pressure)));
  const delta = peak - branch.peakPressure;
  function simulate() {
    setRunning(true);
    timer.current = setTimeout(() => {
      setRun(selected);
      setRunning(false);
    }, 650);
  }
  return (
    <Modal
      title={tr("Change one moment. Rewrite the outcome.")}
      eyebrow="COUNTERFACTUAL / SAME INITIAL STATE"
      onClose={onClose}
      wide
    >
      <p className="modal-intro">
        {" "}{tr("Open an independent cooling bypass and reduce feed. Compare the resulting pressure trajectory with the observed incident.")}{" "}</p>
      <div className="intervention-controls">
        <div>
          <span className="eyebrow">{tr("INTERVENE AT")}</span>
          <div className="segmented">
            {scenario.branches.map((b) => (
              <button
                key={b.time}
                className={selected === b.time ? "selected" : ""}
                aria-pressed={selected === b.time}
                disabled={running}
                onClick={() => setSelected(b.time)}
              >
                +{clock(b.time)}
              </button>
            ))}
          </div>
        </div>
        <button
          className="primary-button"
          disabled={running}
          onClick={simulate}
        >
          <Glyph>{running ? "◌" : "⑂"}</Glyph>
          {running ? tr("Comparing trajectories") : tr("Compare intervention")}
          <span>↗</span>
        </button>
      </div>
      <div
        className={`intervention-verdict ${branch.trip ? "verdict-late" : "verdict-safe"}`}
        role="status"
      >
        <span className="verdict-symbol" aria-hidden="true">
          {branch.trip ? "△" : "⑂"}
        </span>
        <div>
          <span className="eyebrow">
            {!running && tr("AT +{0} / ", {0: clock(run)})}
            {running
              ? tr("COMPARING BRANCHES")
              : branch.trip
                ? tr("TIMING IS THE DIFFERENCE")
                : tr("A DIFFERENT OUTCOME")}
          </span>
          <strong>
            {running
              ? tr("Tracing the alternate trajectory…")
              : branch.trip
                ? tr("Cooling recovers. The threshold is still crossed.")
                : tr("The cascade can be interrupted.")}
          </strong>
        </div>
        <span className="verdict-margin">
          {branch.trip ? "+" : "−"}
          {Math.abs(3050 - branch.peakPressure)}
          <small>kPa {branch.trip ? tr("above") : tr("below")}{" "}{tr("limit")}</small>
        </span>
      </div>
      <div className="compare-legend">
        <span>
          <i className="bg-coral" />{" "}{tr("Observed")}{" "}</span>
        <span>
          <i className="bg-mint" />{" "}{tr("With intervention")}{" "}</span>
        <span className="muted">{tr("REACTOR PRESSURE / kPa")}</span>
      </div>
      <motion.div
        key={run}
        initial={{ opacity: 0.35 }}
        animate={{ opacity: running ? 0.35 : 1 }}
      >
        <TrendChart
          keys={["pressure"]}
          compare={branch.points}
          large
          intervention={run}
          animateComparison
        />
      </motion.div>
      <div className="compare-outcomes">
        <div>
          <span className="eyebrow text-coral">{tr("OBSERVED TRAJECTORY")}</span>
          <strong>
            {peak.toLocaleString()} <small>kPa</small>
          </strong>
          <span>
            <StatusDot tone="coral" />{" "}{tr("Trip threshold exceeded at +")}{" "}{clock(scenario.tripTime)}
          </span>
        </div>
        <div>
          <span className="eyebrow text-mint">
            {" "}{tr("INTERVENTION AT +")}{clock(run)}
          </span>
          <strong className="text-mint">
            {branch.peakPressure.toLocaleString()} <small>kPa</small>
          </strong>
          <span>
            <StatusDot tone={branch.trip ? "amber" : "mint"} />
            {branch.trip
              ? tr("Too late to avoid the trip threshold")
              : tr("Pressure stays below the trip threshold")}
          </span>
        </div>
        <div>
          <span className="eyebrow">{tr("PEAK REDUCTION")}</span>
          <strong>
            −{delta} <small>kPa</small>
          </strong>
          <span>
            {scenario.alarms.length - branch.alarms}{" "}{tr("fewer alarm events")}{" "}</span>
        </div>
      </div>
      <div className="evidence-note">
        <span className="text-mint">└─</span>
        <p>
          {branch.trip
            ? tr("Timing matters. This intervention lowers the final pressure, but the process still crosses 3,050 kPa before cooling recovers.")
            : tr("Earlier cooling recovery interrupts the thermal cascade. The failed valve remains stuck; the independent bypass restores flow.")}
        </p>
      </div>
      <div className="modal-footer">
        <span>
          {" "}{tr("Reduced-order process model · identical prefix · 1 s integration")}{" "}</span>
        <button
          className="subtle-button"
          onClick={() =>
            downloadFile(
              `triplens-intervention-${run}s.json`,
              JSON.stringify(
                {
                  model: scenario.provenance.model,
                  intervention: run,
                  observedPeak: peak,
                  ...branch,
                },
                null,
                2,
              ),
            )
          }
        >
          {" "}{tr("Export comparison ↓")}{" "}</button>
      </div>
    </Modal>
  );
}

export function Help({ onClose }: { onClose: () => void }) {
  useLocale();
  return (
    <Modal
      title={tr("Your incident workstation.")}
      eyebrow="TRIPLENS / QUICK REFERENCE"
      onClose={onClose}
    >
      <div className="help-body">
        <p>
          {" "}{tr("Start a sequence to watch one cooling-loop fault propagate. Inspect any signal, follow the alarm chains, then compare a different intervention time.")}{" "}</p>
        <div className="help-keys">
          {[
            ["Space", tr("Play or pause")],
            ["Ctrl / ⌘ K", tr("Search commands, signals and chapters")],
            ["1 / 2 / 3 / 4 / 5", tr("Live / Investigate / Learn / Replay / Lab")],
            ["R", tr("Restart the sequence")],
            ["?", tr("Open this reference")],
            ["Esc", tr("Close a dialog")],
          ].map(([key, action]) => (
            <div key={key}>
              <kbd>{key}</kbd>
              <span>{action}</span>
            </div>
          ))}
        </div>
        <p className="muted">
          {" "}{tr("The timeline is keyboard accessible. Use the arrow keys when the scrubber is focused. Animations respect your system’s reduced-motion preference.")}{" "}</p>
      </div>
    </Modal>
  );
}
