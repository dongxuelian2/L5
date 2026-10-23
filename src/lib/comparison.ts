import type { Analysis, Incident } from './platform';

export const comparisonCutoffs = [40, 70, 110, 180, 240] as const;
export type CaseView = {
  id: string; title: string; asOf: number; status: string;
  leading: { name: string; score: number; confidence: string };
  detectedAt: number | null;
  alarms: number; conditions: number; clusters: number; repeats: number;
  trustworthyChannels: number; inspectedChannels: number;
  nextMeasurements: string[];
  recovery: { lastRecoverableStart: number | null; modelTrip: number | null } | null;
};

/** Public comparison/export boundary: select the prefix before reading evidence. */
export function viewFor(incident: Incident, asOf: number): CaseView | null {
  if (!comparisonCutoffs.some(t => t === asOf)) return null;
  const analysis: Analysis | undefined = asOf === 240 ? incident : incident.snapshots.find(item => item.time === asOf);
  if (!analysis) return null;
  const d = analysis.diagnosis, a = analysis.alarms;
  const channels = Object.values(d.health);
  return {
    id: incident.id, title: incident.title, asOf, status: d.status,
    leading: { name: d.candidates[0].name, score: d.candidates[0].score, confidence: d.candidates[0].confidence },
    detectedAt: d.firstDetection, alarms: a.eventCount, conditions: a.uniqueConditions,
    clusters: a.clusters.length, repeats: a.reannunciations,
    trustworthyChannels: channels.filter(item => item.usable).length, inspectedChannels: channels.length,
    nextMeasurements: d.nextMeasurements.slice(0, 2).map(item => item.tag),
    recovery: asOf === 240 ? {
      lastRecoverableStart: incident.recovery.actions.map(action => action.latest)
        .filter((value): value is number => value !== null)
        .reduce<number | null>((max, value) => max === null ? value : Math.max(max, value), null),
      modelTrip: incident.recovery.base.trip,
    } : null,
  };
}

export function buildComparisonReport(left: Incident, right: Incident, asOf: number, model: string) {
  if (left.id === right.id) return null;
  const first = viewFor(left, asOf), second = viewFor(right, asOf);
  if (!first || !second) return null;
  return {
    schemaVersion: 1,
    kind: 'time-bounded-simulator-case-comparison', model, asOfSeconds: asOf,
    left: first, right: second,
    limitations: [
      'Both cases use the same reduced-order simulator; this is not independent validation.',
      'Evidence scores are rule support, not calibrated probabilities.',
      'Only evidence through the selected cutoff is compared; recovery is withheld until +240s.',
      'Recovery is conditional simulation without predictive uncertainty bounds or plant actuation advice.',
    ],
  };
}
