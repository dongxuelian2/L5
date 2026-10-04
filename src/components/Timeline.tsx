import { useState } from "react";
import { clock, scenario } from "../lib/engine";
import { Glyph } from "./Primitives";

export function Timeline({
  time,
  playing,
  speed,
  onSeek,
  onToggle,
  onSpeed,
  onReset,
}: {
  time: number;
  playing: boolean;
  speed: number;
  onSeek: (time: number) => void;
  onToggle: () => void;
  onSpeed: () => void;
  onReset: () => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const buckets = Array.from(
    { length: 60 },
    (_, i) =>
      scenario.alarms.filter(
        (event) =>
          Math.min(59, Math.floor(event.t / 5)) === i && event.t <= time,
      ).length,
  );
  const peak = Math.max(1, ...buckets);
  const milestones = [
    { t: 0, name: "Baseline", color: "muted" },
    { t: scenario.faultTime, name: "Fault", color: "mint" },
    {
      t: scenario.detections.pressure.time,
      name: "Propagation",
      color: "amber",
    },
    { t: scenario.tripTime, name: "Trip threshold", color: "coral" },
    { t: 300, name: "End", color: "muted" },
  ];
  return (
    <section
      className="timeline-panel"
      aria-label="Incident playback"
      data-playing={playing}
    >
      <div className="timeline-top">
        <div className="timeline-controls">
          <button
            className="play-button"
            aria-label={playing ? "Pause playback" : "Play incident"}
            onClick={onToggle}
          >
            <Glyph>{playing ? "Ⅱ" : "▶"}</Glyph>
          </button>
          <button
            className="reset-button"
            aria-label="Reset incident"
            onClick={onReset}
          >
            ↺
          </button>
          <span className="time-current">
            {clock(time)} <span>/ 05:00</span>
          </span>
          <button
            className="speed-button"
            onClick={onSpeed}
            aria-label={`Playback speed ${speed}x, change speed`}
          >
            {speed}×
          </button>
        </div>
        <span className="timeline-label">
          <span className="timeline-density-label">ALARM DENSITY / 5s</span>{" "}
          <kbd>SPACE</kbd>
          <span className="desktop-only"> to {playing ? "pause" : "play"}</span>
        </span>
      </div>
      <div className="timeline-track">
        <div className="timeline-density" aria-hidden="true">
          {buckets.map((count, index) => (
            <span
              key={index}
              className={index * 5 <= time ? "observed" : ""}
              style={{ height: `${2 + (16 * count) / peak}px` }}
            />
          ))}
        </div>
        <div className="timeline-rail">
          <div
            className="timeline-progress"
            style={{ width: `${time / 3}%` }}
          />
        </div>
        {milestones.map((m) => (
          <span
            key={m.t}
            className={`timeline-tick text-${m.color}`}
            style={{ left: `${m.t / 3}%` }}
          />
        ))}
        <input
          type="range"
          min="0"
          max="300"
          step="1"
          value={Math.floor(time)}
          onChange={(event) => onSeek(Number(event.target.value))}
          aria-label="Incident time in seconds"
          aria-valuetext={`${clock(time)} of 05:00`}
          onPointerMove={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            setHover(
              Math.max(
                0,
                Math.min(
                  300,
                  Math.round(((event.clientX - rect.left) / rect.width) * 300),
                ),
              ),
            );
          }}
          onPointerLeave={() => setHover(null)}
          onBlur={() => setHover(null)}
        />
        {hover !== null && (
          <span
            className="timeline-hover"
            style={{ left: `${Math.min(97, Math.max(3, hover / 3))}%` }}
          >
            +{clock(hover)}
          </span>
        )}
      </div>
      <div className="timeline-markers">
        {milestones.map((m) => (
          <button
            key={m.t}
            className={`text-${m.color} ${time >= m.t ? "reached" : ""}`}
            onClick={() => onSeek(m.t)}
          >
            <span>{m.name}</span>
            <span>+{clock(m.t)}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
