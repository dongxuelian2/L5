import type { Interval } from "./types";

// Presentation priority only: never filter, merge or mutate the detection records.
export function keyFindings(intervals: Interval[], count = 3): Interval[] {
  return [...intervals].sort((a, b) => b.samples - a.samples || b.peakScore - a.peakScore || a.start - b.start).slice(0, count);
}

export function intervalWindow(interval: Interval, full: [number, number]): [number, number] {
  const padding = Math.max(5, (interval.end - interval.start) * .15);
  return [Math.max(full[0], interval.start - padding), Math.min(full[1], interval.end + padding)];
}
