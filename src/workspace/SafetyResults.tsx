import { useState } from "react";
import { t as tr } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { Plot } from "./Charts";
import { tankSignalLabels, uncertaintyLabels } from "./SafetyEditors";
import type { SafetyAssessment, SafetyDefinition, SafetyEvidence, SafetyForecast, SafetyInterval, SafetyObservation, SafetySeries, SafetyState } from "./safetyTypes";
import { dateLabel, number, signalLabel, timeLabel, type Signal, type TimeAxis } from "./types";

const stateLabels: Record<SafetyState, string> = { normal: "Within limits", warning: "Warning", violation: "Violation", unavailable: "Unavailable" };
const stateColors = { normal: "#b5ed9a", warning: "#e2bc75", violation: "#e9927d", unavailable: "#a8afbf" };
const forecastLabels = { crossing: "Crossing predicted", "no-crossing": "No crossing in horizon", unavailable: "Forecast unavailable" };
const forecastReasons: Record<string, string> = {
  "unsupported-model": "Choose a raw coupled-tank simulation Dataset.",
  "unsupported-model-version": "The saved tank model version is unavailable.",
  "invalid-model-parameters": "Saved tank model parameters are invalid.",
  "incompatible-measurement-unit": "Required level and input measurements must retain their native model units.",
  "no-prior-observation": "No measurement exists at or before this cutoff.",
  "ambiguous-observation": "The latest timestamp has duplicate observations.",
  "stale-observation": "The latest observation is older than the permitted age.",
  "missing-observation": "A measured level or control input is unavailable at the latest timestamp.",
  "invalid-observation": "A measured level or control input falls outside the tank model domain.",
  "scenario-outside-model-domain": "The scenario inputs fall outside the tank model domain.",
  "numerical-check": "The model trajectory did not pass a numerical check.",
  "signal-outside-model": "The model cannot project a signal used by this constraint.",
  "incomplete-constraint-trajectory": "Part of the predicted constraint trajectory is unavailable.",
};
const numberOrDash = (value?: number | null) => value == null ? "—" : number(value);
const inUnits = (value: number | null | undefined, unit: string) => value == null ? "—" : `${number(value)} ${unit}`;
const percentage = (value?: number | null) => value == null ? "—" : `${number(value * 100)}%`;
const displayTime = (axis: TimeAxis, value?: number | null) => value == null ? "—" : timeLabel(axis, value);
const forecastReason = (reasonCode?: string, reason?: string) => reasonCode && forecastReasons[reasonCode] ? tr(forecastReasons[reasonCode]) : reason ? errorMessage(reason) : "";

function State({ state }: { state?: SafetyState }) {
  const status = state || "unavailable";
  return <span className={`safety-state safety-${status}`}><i aria-hidden="true" />{tr(stateLabels[status])}</span>;
}

function closestTime(times: number[], time: number) {
  let start = 0, end = times.length - 1;
  while (start < end) {
    const middle = (start + end) >> 1;
    if (times[middle] < time) start = middle + 1; else end = middle;
  }
  return start > 0 && time - times[start - 1] < times[start] - time ? start - 1 : start;
}

function SafetyPlot({ definition, series, axis, intervals, gaps, selectedTime, onSelectTime }: {
  definition: SafetyDefinition; series: SafetySeries; axis: TimeAxis; intervals: SafetyInterval[];
  gaps?: SafetyObservation["quality"]["gaps"]; selectedTime?: number; onSelectTime?: (time: number) => void;
}) {
  const times = series.times.length === 1 ? [series.times[0], series.times[0] + 1] : [series.times[0], series.times.at(-1)!];
  const boundaries = [
    [definition.lower, "Critical lower limit", stateColors.violation], [definition.upper, "Critical upper limit", stateColors.violation],
    [definition.warningLower, "Lower warning boundary", stateColors.warning], [definition.warningUpper, "Upper warning boundary", stateColors.warning],
  ] as const;
  const overlays = boundaries.flatMap(([value, label, color]) => value == null ? [] : [{ times, values: [value, value], segmentIds: [0, 0], title: tr(label), color }]);
  const bands = intervals.map(interval => ({ start: interval.start, end: interval.end, label: tr(stateLabels[interval.state]), color: stateColors[interval.state] }));
  return <>
    <Plot title={`${definition.name} (${definition.unit})`} times={series.times} values={series.values} axis={axis} segmentIds={series.segmentIds}
      overlays={overlays} bands={bands} gaps={gaps} selectedTime={selectedTime} onSelectTime={onSelectTime} showIsolatedSamples
      timeDomain={series.times.length === 1 ? [times[0], times[1]] : undefined} />
    <ul className="safety-boundary-key" aria-label={tr("Constraint boundaries")}>{boundaries.map(([value, label, color]) => value == null ? null :
      <li key={label}><i style={{ background: color }} aria-hidden="true" />{tr(label)} {inUnits(value, definition.unit)}</li>)}</ul>
  </>;
}

function IntervalTable({ intervals, axis, unit, marginUnit, selectedIndex, onSelect, onAttach }: {
  intervals: SafetyInterval[]; axis: TimeAxis; unit: string; marginUnit: string; selectedIndex?: number;
  onSelect?: (index: number, time: number) => void; onAttach?: (index: number) => void;
}) {
  if (!intervals.length) return <p className="ws-muted">{tr("No intervals recorded.")}</p>;
  return <div className="ws-table-scroll safety-table"><table><thead><tr>
    {["State", "Start", "End", "Duration (s)", "Samples", "Peak value", "Maximum exceedance", "Confirmed at"].map(label => <th key={label}>{tr(label)}</th>)}
    {(onSelect || onAttach) && <th>{tr("Actions")}</th>}
  </tr></thead><tbody>{intervals.map((interval, index) => <tr key={index} data-selected={selectedIndex === index || undefined}>
    <td><State state={interval.state} /></td><td>{displayTime(axis, interval.start)}</td><td>{displayTime(axis, interval.end)}</td>
    <td>{numberOrDash(interval.duration)}</td><td>{interval.samples}</td><td>{inUnits(interval.peakValue, unit)}</td>
    <td>{inUnits(interval.maximumExceedance, marginUnit)}</td><td>{displayTime(axis, interval.confirmedAt)}</td>
    {(onSelect || onAttach) && <td><div className="safety-actions">
      {onSelect && <button type="button" onClick={() => onSelect(index, interval.peakTime ?? interval.start)}>{tr("Inspect")}</button>}
      {onAttach && interval.state === "violation" && <button type="button" onClick={() => onAttach(index)}>{tr("Attach to Incident")}</button>}
    </div></td>}
  </tr>)}</tbody></table></div>;
}

function MeasurementEvidence({ observation, axis, signals, selectedTime }: {
  observation: SafetyObservation; axis: TimeAxis; signals: Signal[]; selectedTime: number;
}) {
  const { series, constraint } = observation;
  if (!series.times.length) return null;
  const index = closestTime(series.times, selectedTime);
  return <div className="safety-evidence">
    <h4>{tr("Measurement evidence")} · {displayTime(axis, series.times[index])}</h4>
    <dl>
      <div><dt>{tr("Constraint value")}</dt><dd>{inUnits(series.values[index], constraint.unit)}</dd></div>
      <div><dt>{tr("Operating margin")}</dt><dd>{inUnits(series.margins[index], observation.marginUnit)}</dd></div>
      <div><dt>{tr("Policy state")}</dt><dd><State state={series.states[index]} /></dd></div>
      <div><dt>{tr("Numerical state")}</dt><dd><State state={series.rawStates[index]} /></dd></div>
      {Object.entries(series.measurements || {}).map(([id, values]) => {
        const signal = signals.find(candidate => candidate.id === id);
        const missing = values[index] == null;
        const unobserved = !missing && series.measurementObserved?.[id]?.[index] === false;
        return <div key={id}><dt>{signal ? signalLabel(signal) : id}</dt><dd>{inUnits(values[index], observation.sourceUnits[id] || "")}{unobserved && ` · ${tr("Unobserved")}`}</dd></div>;
      })}
    </dl>
  </div>;
}

function ObservationView({ observation, axis, signals, canAttach, attach }: {
  observation: SafetyObservation; axis: TimeAxis; signals: Signal[]; canAttach: boolean; attach: (evidence: SafetyEvidence) => void;
}) {
  const [selection, setSelection] = useState<{ time: number; interval?: number; raw?: boolean } | null>(null);
  const { constraint, current, coverage, quality, intervals, rawViolationIntervals, series, marginUnit } = observation;
  const selectedTime = selection?.time ?? current?.time;
  return <div className="safety-observation">
    <div className="safety-summary">
      <div><span>{tr("Latest observed state")}</span><strong><State state={current?.state} /></strong></div>
      <div><span>{tr("Current observed margin")}</span><strong>{inUnits(current?.margin, marginUnit)}</strong></div>
      <div><span>{tr("Minimum observed margin")}</span><strong>{inUnits(observation.minimumMargin, marginUnit)}</strong></div>
      <div><span>{tr("Violation duration (s)")}</span><strong>{numberOrDash(observation.violationDuration)}</strong></div>
    </div>
    {current?.duplicateTimestamp && <p className="ws-notice">{tr("The latest timestamp has duplicate observations.")}</p>}
    <SafetyPlot definition={constraint} series={series} axis={axis} intervals={[...intervals.filter(item => item.state !== "violation"), ...rawViolationIntervals]} gaps={quality.gaps}
      selectedTime={selectedTime} onSelectTime={time => setSelection({ time })} />
    {selectedTime != null && <MeasurementEvidence observation={observation} axis={axis} signals={signals} selectedTime={selectedTime} />}
    {constraint.kind !== "value" && Object.keys(series.measurements || {}).length > 0 && <details>
      <summary>{tr("Synchronized signal measurements")}</summary>
      {Object.entries(series.measurements || {}).map(([id, values]) => {
        const signal = signals.find(candidate => candidate.id === id);
        return <Plot key={id} title={signal ? signalLabel(signal) : id} times={series.times} values={values} axis={axis} gaps={quality.gaps}
          segmentIds={series.segmentIds} selectedTime={selectedTime} onSelectTime={time => setSelection({ time })} />;
      })}
    </details>}
    <div className="safety-evidence">
      <h4>{tr("Observation coverage")}</h4>
      <dl>
        <div><dt>{tr("Evaluated samples")}</dt><dd>{coverage.evaluatedSamples} / {coverage.totalSamples} · {percentage(coverage.sampleFraction)}</dd></div>
        <div><dt>{tr("Covered time")}</dt><dd>{inUnits(coverage.observedDuration, "s")} · {percentage(coverage.durationFraction)}</dd></div>
        <div><dt>{tr("Missing samples")}</dt><dd>{quality.missingSamples}</dd></div>
        <div><dt>{tr("Unobserved samples")}</dt><dd>{quality.unobservedSamples}</dd></div>
        <div><dt>{tr("Acquisition gaps")}</dt><dd>{quality.gaps.length}</dd></div>
        <div><dt>{tr("Duplicate timestamps")}</dt><dd>{quality.duplicateCount}</dd></div>
        <div><dt>{tr("Unavailable rate samples")}</dt><dd>{quality.rateUnavailableSamples}</dd></div>
        <div><dt>{tr("Unavailable numerical samples")}</dt><dd>{quality.numericalUnavailableSamples}</dd></div>
      </dl>
    </div>
    <h3>{tr("Observed policy intervals")}</h3>
    <IntervalTable intervals={intervals} axis={axis} unit={constraint.unit} marginUnit={marginUnit} selectedIndex={selection?.raw ? undefined : selection?.interval}
      onSelect={(interval, time) => setSelection({ time, interval })}
      onAttach={canAttach ? intervalIndex => attach({ kind: "observed", constraintId: constraint.id, intervalIndex }) : undefined} />
    <details><summary>{tr("Raw critical exceedances")} ({rawViolationIntervals.length})</summary>
      <p className="ws-muted">{tr("Includes single observations and exceedances shorter than the configured dwell.")}</p>
      <IntervalTable intervals={rawViolationIntervals} axis={axis} unit={constraint.unit} marginUnit={marginUnit} selectedIndex={selection?.raw ? selection.interval : undefined}
        onSelect={(interval, time) => setSelection({ time, interval, raw: true })}
        onAttach={canAttach ? intervalIndex => attach({ kind: "observed", constraintId: constraint.id, intervalIndex, raw: true }) : undefined} />
    </details>
  </div>;
}

function ForecastView({ forecast, definitions, axis, selectedId, canAttach, attach }: {
  forecast: SafetyForecast; definitions: SafetyDefinition[]; axis: TimeAxis; selectedId: string; canAttach: boolean; attach: (evidence: SafetyEvidence) => void;
}) {
  const [selectedTime, setSelectedTime] = useState<number>();
  const [selectedInterval, setSelectedInterval] = useState<number>();
  const [trajectorySignal, setTrajectorySignal] = useState("level1");
  const focused = forecast.constraints.find(item => item.constraintId === selectedId);
  const definition = definitions.find(item => item.id === selectedId);
  const trajectory = forecast.trajectory;
  const inlet = forecast.assumptions.observedInputComparison;
  return <section className="ws-panel safety-results" aria-labelledby="safety-forecast-result-title">
    <h2 id="safety-forecast-result-title">{tr("Predictive risk")}</h2>
    <p className="ws-muted">{tr("Time to Constraint Violation (TCV) is the elapsed time to the first predicted violation under the selected assumptions.")}</p>
    <div className="safety-summary">
      <div><span>{tr("Forecast status")}</span><strong>{tr({ available: "Forecast available", unavailable: "Forecast unavailable", unreliable: "Forecast unreliable" }[forecast.status])}</strong></div>
      <div><span>{tr("Prediction cutoff")}</span><strong>{displayTime(axis, forecast.requestedAsOf)}</strong></div>
      <div><span>{tr("Latest input observation")}</span><strong>{displayTime(axis, forecast.observedThrough)}</strong></div>
      {forecast.model && <div><span>{tr("Model version")}</span><strong>{forecast.model.id} · v{forecast.model.version}</strong></div>}
    </div>
    {(forecast.reasonCode || forecast.reason) && <p className="ws-notice" role="status">{forecastReason(forecast.reasonCode, forecast.reason)}</p>}
    {inlet && <p className="ws-muted">{tr("At the latest observed pump command, measured inlet flow was {0} and modeled inlet flow was {1}.", { 0: inUnits(inlet.measuredInlet, inlet.unit), 1: inUnits(inlet.modeledInlet, inlet.unit) })}</p>}
    {forecast.constraints.length > 0 && <div className="ws-table-scroll safety-table"><table><thead><tr>
      {["Constraint", "Forecast status", "Latest input margin", "TCV (s)", "First crossing", "Minimum predicted margin", "Maximum exceedance", "Violation duration (s)"].map(label => <th key={label}>{tr(label)}</th>)}
    </tr></thead><tbody>{forecast.constraints.map(item => {
      const constraint = definitions.find(candidate => candidate.id === item.constraintId);
      const unit = item.marginUnit || constraint?.unit || "";
      return <tr key={item.constraintId} data-selected={selectedId === item.constraintId || undefined}><td>{constraint?.name || item.constraintId}</td>
        <td className={item.status === "crossing" ? "ws-coral" : undefined}>{tr(item.startedInViolation ? "Violation at forecast start" : forecastLabels[item.status])}
          {item.reasonCode && <p className="ws-muted">{forecastReason(item.reasonCode)}</p>}</td><td>{inUnits(item.currentMargin, unit)}</td>
        <td>{numberOrDash(item.timeToViolation)}</td><td>{displayTime(axis, item.firstCrossingTime)}</td><td>{inUnits(item.minimumMargin, unit)}</td>
        <td>{inUnits(item.maximumExceedance, unit)}</td><td>{numberOrDash(item.violationDuration)}</td></tr>;
    })}</tbody></table></div>}
    {focused?.series && definition && <>
      <SafetyPlot definition={definition} series={focused.series} intervals={focused.intervals} axis={axis} selectedTime={selectedTime} onSelectTime={setSelectedTime} />
      <Plot title={`${tr("Predicted operating margin")} (${focused.marginUnit || definition.unit})`} times={focused.series.times} values={focused.series.margins} axis={axis}
        segmentIds={focused.series.segmentIds} threshold={0} thresholdLabel={tr("Critical limit")} selectedTime={selectedTime} onSelectTime={setSelectedTime} />
      <h3>{tr("Predicted violation intervals")}</h3>
      <IntervalTable intervals={focused.intervals} axis={axis} unit={definition.unit} marginUnit={focused.marginUnit || definition.unit} selectedIndex={selectedInterval}
        onSelect={(index, time) => { setSelectedInterval(index); setSelectedTime(time); }}
        onAttach={canAttach ? intervalIndex => attach({ kind: "predicted", constraintId: definition.id, intervalIndex }) : undefined} />
    </>}
    {trajectory && <div className="safety-trajectory">
      <label>{tr("Predicted trajectory signal")}<select value={trajectorySignal} onChange={event => setTrajectorySignal(event.target.value)}>
        {Object.keys(trajectory.values).map(key => <option key={key} value={key}>{tr(tankSignalLabels[key]?.[0] || key)}</option>)}
      </select></label>
      {trajectory.values[trajectorySignal] && <Plot title={`${tr(tankSignalLabels[trajectorySignal]?.[0] || trajectorySignal)} (${tr(trajectory.units?.[trajectorySignal] || tankSignalLabels[trajectorySignal]?.[1] || "")})`}
        times={trajectory.times} values={trajectory.values[trajectorySignal]} axis={axis} selectedTime={selectedTime} onSelectTime={setSelectedTime} />}
    </div>}
    {forecast.uncertainty && <UncertaintyView uncertainty={forecast.uncertainty} definitions={definitions} axis={axis} selectedId={selectedId}
      marginUnits={Object.fromEntries(forecast.constraints.map(item => [item.constraintId, item.marginUnit || ""]))} />}
    <details><summary>{tr("Model parameters, input measurements and assumptions")}</summary><pre>{JSON.stringify({ model: forecast.model, inputMeasurements: forecast.inputMeasurements, assumptions: forecast.assumptions }, null, 2)}</pre></details>
  </section>;
}

function UncertaintyView({ uncertainty, definitions, axis, selectedId, marginUnits }: {
  uncertainty: NonNullable<SafetyForecast["uncertainty"]>; definitions: SafetyDefinition[]; axis: TimeAxis; selectedId: string; marginUnits: Record<string, string>;
}) {
  const [scenarioId, setScenarioId] = useState("");
  const selected = uncertainty.constraints.find(item => item.constraintId === selectedId);
  const unit = marginUnits[selectedId] || "";
  const scenario = uncertainty.scenarios.find(item => String(item.id) === scenarioId);
  return <div className="safety-uncertainty">
    <h3>{tr("Sensitivity and uncertainty")}</h3>
    <p className="ws-muted">{tr("{0} sampled scenarios · seed {1}. Crossing fractions describe the evaluated scenarios only.", { 0: uncertainty.samples, 1: uncertainty.seed })}</p>
    <div className="ws-table-scroll safety-table"><table><thead><tr>
      {["Constraint", "Evaluated scenarios", "Unavailable scenarios", "Crossing fraction", "Earliest crossing", "Latest crossing", "Worst margin"].map(label => <th key={label}>{tr(label)}</th>)}
    </tr></thead><tbody>{uncertainty.constraints.map(item => {
      const definition = definitions.find(candidate => candidate.id === item.constraintId);
      return <tr key={item.constraintId} data-selected={selectedId === item.constraintId || undefined}>
        <td>{definition?.name || item.constraintId}</td><td>{item.evaluatedScenarios}</td><td>{item.unavailableScenarios}</td>
        <td>{percentage(item.violationFraction)} ({item.crossingScenarios}/{item.evaluatedScenarios})</td><td>{displayTime(axis, item.earliestCrossingTime)}</td>
        <td>{displayTime(axis, item.latestCrossingTime)}</td><td>{inUnits(item.worstMargin, marginUnits[item.constraintId] || "")}</td>
      </tr>;
    })}</tbody></table></div>
    {!!selected?.sensitivity?.length && <div className="ws-table-scroll safety-table"><table><caption>{tr("One-parameter sensitivity for the selected constraint")}</caption><thead><tr>
      {["Parameter", "Lower deviation", "Upper deviation", "Margin at lower deviation", "Margin at upper deviation", "Margin change"].map(label => <th key={label}>{tr(label)}</th>)}
    </tr></thead><tbody>{selected.sensitivity.map(item => <tr key={item.parameter}>
      <td>{tr(uncertaintyLabels[item.parameter]?.[0] || item.parameter)}</td><td>{numberOrDash(item.lowerValue)}</td><td>{numberOrDash(item.upperValue)}</td>
      <td>{inUnits(item.lowerMargin, unit)}</td><td>{inUnits(item.upperMargin, unit)}</td><td>{inUnits(item.marginChange, unit)}</td>
    </tr>)}</tbody></table></div>}
    {!!uncertainty.scenarios.length && <details><summary>{tr("Inspect a sampled scenario")}</summary>
      <label>{tr("Scenario")}<select value={scenarioId} onChange={event => setScenarioId(event.target.value)}>
        <option value="">{tr("Choose a scenario")}</option>{uncertainty.scenarios.map(item => <option key={item.id} value={String(item.id)}>{item.id} · {tr(item.status === "available" ? "Available" : item.status === "unreliable" ? "Unreliable" : "Unavailable")}</option>)}
      </select></label>
      {scenario && <><dl className="safety-perturbations">{Object.entries(scenario.perturbations).map(([key, value]) => {
        const [label, unit] = uncertaintyLabels[key as keyof typeof uncertaintyLabels] || [key, ""];
        return <div key={key}><dt>{tr(label)}</dt><dd>{inUnits(value, tr(unit))}</dd></div>;
      })}</dl>
      {(scenario.reasonCode || scenario.reason) && <p>{forecastReason(scenario.reasonCode, scenario.reason)}</p>}
      {scenario.constraints.map(item => {
        const definition = definitions.find(candidate => candidate.id === item.constraintId);
        return <p key={item.constraintId}>{definition?.name || item.constraintId} · {tr(forecastLabels[item.status])} · {tr("TCV (s)")} {numberOrDash(item.timeToViolation)} · {tr("Minimum predicted margin")} {inUnits(item.minimumMargin, marginUnits[item.constraintId] || "")}</p>;
      })}</>}
    </details>}
  </div>;
}

export function SafetyResults({ assessment, axis, signals, attach, controls }: {
  assessment: SafetyAssessment; axis: TimeAxis; signals: Signal[]; attach: (evidence: SafetyEvidence) => void; controls?: React.ReactNode;
}) {
  const [selected, setSelected] = useState(assessment.observed[0]?.constraint.id || "");
  const observation = assessment.observed.find(item => item.constraint.id === selected) || assessment.observed[0];
  return <>
    <section className="ws-panel safety-results" aria-labelledby="safety-observation-title">
      <div className="ws-section-heading"><div><h2 id="safety-observation-title">{tr("Observed constraint assessment")}</h2>
        <p>{assessment.name} · {dateLabel(assessment.createdAt)}{assessment.configuration.revision ? ` · ${tr("Configuration revision")} ${assessment.configuration.revision}` : ""}</p></div>{controls}</div>
      <p className="ws-muted">{tr("Results use all source observations. Positive margins are within the critical boundaries.")}</p>
      <div className="ws-table-scroll safety-table"><table><thead><tr>
        {["Constraint", "Latest observed state", "Current observed margin", "Minimum observed margin", "Maximum exceedance", "Observation coverage"].map(label => <th key={label}>{tr(label)}</th>)}
      </tr></thead><tbody>{assessment.observed.map(item => <tr key={item.constraint.id} data-selected={observation?.constraint.id === item.constraint.id || undefined}>
        <td><button type="button" className="safety-constraint-link" aria-pressed={observation?.constraint.id === item.constraint.id} onClick={() => setSelected(item.constraint.id)}>{item.constraint.name}</button>
          {item.constraint.equipment && <span className="ws-muted">{item.constraint.equipment}</span>}</td><td><State state={item.current?.state} /></td>
        <td>{inUnits(item.current?.margin, item.marginUnit)}</td><td>{inUnits(item.minimumMargin, item.marginUnit)}</td>
        <td>{inUnits(item.maximumExceedance, item.marginUnit)}</td><td>{percentage(item.coverage.sampleFraction)}</td>
      </tr>)}</tbody></table></div>
      {observation && <ObservationView key={observation.constraint.id} observation={observation} axis={axis} signals={signals} canAttach={Boolean(assessment.id)} attach={attach} />}
      {!assessment.id && <p className="ws-muted">{tr("Save the assessment to export results or attach violation evidence to an Incident.")}</p>}
    </section>
    {assessment.forecast && <ForecastView key={observation?.constraint.id} forecast={assessment.forecast} definitions={assessment.configuration.constraints}
      axis={axis} selectedId={observation?.constraint.id || ""} canAttach={Boolean(assessment.id)} attach={attach} />}
  </>;
}
