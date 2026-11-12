# Alarm Management

Open **Alarm workspace** in a Workspace with saved analyses. Select the results and
generate a named session. A session saves the selected source references,
clock snapshots, engineering policy, original events, and correlated groups.
Reopen it from the same Workspace after a restart. To compare policies, generate
another session with a different configuration.

## Configure a session

- Assign priorities to specific Dataset signals and map signals to equipment.
  The mapping and configured priority order determine presentation priority.
- Set the correlation window and add relationships between Dataset signals.
  Equipment grouping is optional. Enable it where a shared unit is meaningful
  evidence of association.
- Set a repeat window for recurring alarms and persistence requirements for
  operator attention. Events below persistence remain inspectable.
- Set the maximum shelf duration, an optional unacknowledged escalation delay,
  and the alarm-load window in seconds.

Expand a group to see each original alarm and the relationships supporting the
group. Signal evidence uses the leading saved detector contributions, including
ties, or the first ranked source signal for older results without contributions.
Each event retains the full saved signal and contribution lists. Close events
require observation coverage across the gap. Correlation can connect alarms
through intermediate members. The recorded edges explain those links. Treat a
group as a set of candidates for investigation. Establishing physical causality
requires process evidence.

UTC datasets share an absolute axis. Relative datasets share an axis only if
their saved time references establish one. The session freezes those
references at generation. Each event retains its source-native times, detector
threshold and evidence, source interval index, and normalized coordinates.
Point alarms have zero measured duration. Gaps and abstentions break event
continuity, and a cutoff without a follow-up observation can leave the ending
uncertain.

## Work with alarms

Inspect a group's events and use the shared time cursor to compare the score
with source measurements. Filter the timeline by axis, time range, source,
priority, or state. An acknowledgement records an operator action alongside
the detector's measured state. A shelf expires automatically and affects the
operator queue. Notes and Incident associations are recorded in session history
along with action time and operator identity. An escalated alarm is flagged in
the application.

Create an Incident from a group or link the group to an existing Incident in
the Workspace. The Incident's regular timeline and reporting tools carry the
dataset and original detector interval references alongside group evidence
and operator observations recorded at the time of linking. Export the session
for a machine-readable history or an offline report.

## Read alarm load

Arrival counts use event starts. Group arrivals use each group's earliest
start. The dashboard displays each compatible axis independently. Windows
are left-closed and right-open, anchored to the earliest selected analysis
start on that axis. A rate in alarms/hour scales the count by
`3600 / windowSeconds`. Concurrent activity uses closed observed event
intervals, so a point alarm counts at its timestamp. Duration is the difference
between the first and last alarm samples. The repeat count adds all arrivals
after the first for each Dataset, detector, and affected signal set on an axis.
Signal and equipment distributions can count the same alarm under multiple
affected signals or equipment.
Acknowledgement delay uses elapsed operator time since session generation and
includes acknowledged events only.

## Reproduce the evaluation

```sh
node scripts/python.mjs -m benchmarks.alarm_correlation
```

The benchmark scripts physical incidents and background excursions, then builds
saved-result-shaped detector traces. The declared cause labels stay outside
the engine. Pair counts compare the group memberships with those labels. A
pair from different causes in one group is a merge error. A pair from one
cause in different groups is a split error. A true pair across an acquisition
blackout can remain split because the observations cannot establish continuity.
The benchmark also enables equipment grouping to show how a bearing fault and
a valve jam on one skid can be associated by a broader policy.
Preservation checks account for both event membership and alarm samples. The
benchmark reports event and group counts as two measures of review workload,
along with processing time, peak window arrivals, and peak concurrency. Runtime
depends on the machine.

| Scenario | Source alarms | Groups | Incorrect merge pairs | Incorrect split pairs |
|---|---:|---:|---:|---:|
| Close and overlapping faults | 12 | 8 | 0 | 1 |
| Same traces with equipment grouping | 12 | 7 | 5 | 1 |
| Flood across four equipment groups | 3,900 | 1,500 | 0 | 0 |

The flood peaks at 78 source alarms in a 60-second window and 12 concurrent
alarms. All three evaluations preserve every source event and alarm sample.
