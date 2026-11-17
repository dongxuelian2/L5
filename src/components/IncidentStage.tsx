import { t as tr } from "../lib/text";
import { motion, AnimatePresence } from "motion/react";
import { clock, scenario } from "../lib/engine";
import { ScrambleText } from "./Primitives";

export const chapters = [
  {
    time: 0,
    get label() { return "Baseline"; },
    get title() { return "A process in balance."; },
    get detail() { return "Six signals are holding within their operating baseline."; },
    tone: "mint",
  },
  {
    time: scenario.faultTime,
    get label() { return "Disturbance"; },
    get title() { return "One valve changes the story."; },
    get detail() { return "Cooling-valve position changes. Waiting for confirmed signal deviation."; },
    tone: "amber",
  },
  {
    time: scenario.detections.valve.time,
    get label() { return "Detection"; },
    get title() { return "The first signal breaks away."; },
    get detail() { return "CV-101 deviates first. Follow the cooling loop downstream."; },
    tone: "mint",
  },
  {
    time: scenario.detections.purity.time,
    get label() { return "Evidence"; },
    get title() { return "The cascade has an origin."; },
    get detail() { return "All six signals have deviated. Five ordered paths connect the evidence."; },
    tone: "amber",
  },
  {
    time: scenario.tripTime,
    get label() { return "Threshold"; },
    get title() { return "Pressure crosses the trip limit."; },
    get detail() { return "3,050 kPa exceeded. Compare an earlier intervention to change the trajectory."; },
    tone: "coral",
  },
  {
    time: scenario.duration,
    get label() { return "Complete"; },
    get title() { return "Now change one moment."; },
    get detail() { return "The observed sequence is complete. Test when the cooling bypass changes the outcome."; },
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
  const index = chapters.reduce(
    (last, chapter, i) => (time >= chapter.time ? i : last),
    0,
  );
  const stage = chapters[Math.max(index, 0)];
  return (
    <section
      className={`incident-stage stage-${stage.tone}`}
      aria-label={"Incident chapter"}
    >
      <div className="stage-index">
        <span>CHAPTER</span>
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
      <div className="chapter-navigation" aria-label={"Jump to chapter"}>
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
