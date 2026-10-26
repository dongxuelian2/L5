import { t as tr, useLocale } from "../i18n";
import { motion, AnimatePresence } from "motion/react";
import { clock, scenario } from "../lib/engine";
import { ScrambleText } from "./Primitives";

export const chapters = [
  {
    time: 0,
    get label() { return tr("Baseline"); },
    get title() { return tr("A process in balance."); },
    get detail() { return tr("Six signals are holding within their operating baseline."); },
    tone: "mint",
  },
  {
    time: scenario.faultTime,
    get label() { return tr("Disturbance"); },
    get title() { return tr("One valve changes the story."); },
    get detail() { return tr("Cooling-valve position changes. Waiting for confirmed signal deviation."); },
    tone: "amber",
  },
  {
    time: scenario.detections.valve.time,
    get label() { return tr("Detection"); },
    get title() { return tr("The first signal breaks away."); },
    get detail() { return tr("CV-101 deviates first. Follow the cooling loop downstream."); },
    tone: "mint",
  },
  {
    time: scenario.detections.purity.time,
    get label() { return tr("Evidence"); },
    get title() { return tr("The cascade has an origin."); },
    get detail() { return tr("All six signals have deviated. Five ordered paths connect the evidence."); },
    tone: "amber",
  },
  {
    time: scenario.tripTime,
    get label() { return tr("Threshold"); },
    get title() { return tr("Pressure crosses the trip limit."); },
    get detail() { return tr("3,050 kPa exceeded. Compare an earlier intervention to change the trajectory."); },
    tone: "coral",
  },
  {
    time: scenario.duration,
    get label() { return tr("Complete"); },
    get title() { return tr("Now change one moment."); },
    get detail() { return tr("The observed sequence is complete. Test when the cooling bypass changes the outcome."); },
    tone: "violet",
  },
] as const;

export function IncidentStage({
  time,
  onSeek,
}: {
  time: number;
  onSeek: (time: number) => void;
}) {
  useLocale();
  const index = chapters.reduce(
    (last, chapter, i) => (time >= chapter.time ? i : last),
    0,
  );
  const stage = chapters[Math.max(index, 0)];
  return (
    <section
      className={`incident-stage stage-${stage.tone}`}
      aria-label={tr("Incident chapter")}
    >
      <div className="stage-index">
        <span>{tr("CHAPTER")}</span>
        <strong>
          {String(index + 1).padStart(2, "0")}
          <small>/06</small>
        </strong>
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={index}
          className="stage-copy"
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -3 }}
          transition={{ duration: 0.18 }}
        >
          <h2>
            <ScrambleText text={stage.title} />
          </h2>
          <p>{stage.detail}</p>
        </motion.div>
      </AnimatePresence>
      <div className="chapter-navigation" aria-label={tr("Jump to chapter")}>
        {chapters.map((chapter, i) => (
          <button
            key={chapter.label}
            onClick={() => onSeek(chapter.time)}
            aria-label={tr("Jump to {0}, {1}", {0: chapter.label, 1: clock(chapter.time)})}
            aria-current={index === i ? "step" : undefined}
            className={`${i === index ? "current" : ""} ${i <= index ? "reached" : ""}`}
            title={`${chapter.label} · +${clock(chapter.time)}`}
          >
            <span className="chapter-line" />
            <span>{String(i + 1).padStart(2, "0")}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
