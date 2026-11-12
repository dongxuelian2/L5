import { useState } from "react";
import { t as tr } from "../i18n";
import { Plot } from "./Charts";
import { forecastStatus, modelName } from "./prognosticLabels";
import type { Evaluation, EvaluationGroup, FitResult, Forecast, ForecastStatus, MaintenanceOption } from "./prognosticTypes";
import { number, timeLabel, type TimeAxis } from "./types";

const actionNames: Record<MaintenanceOption["action"], string> = {
  continue: "Continue operating",
  preventive: "Restore now",
  schedule: "Schedule restoration",
  replace: "Replace now",
  corrective: "Corrective maintenance",
};
const diagnosticNames: Record<string, string> = {
  n_observations: "Usable measurements",
  n_missing: "Missing measurements",
  drift: "Fitted drift per second",
  drift_interval: "Drift parameter interval",
  process_variance_rate: "Process variance per second",
  measurement_sd: "Measurement noise standard deviation",
  residual_rmse: "Fitted residual RMSE",
  n_distinct_times: "Distinct measurement times",
  n_load_measurements: "Load measurements",
  load_range: "Observed load range",
  operating_periods: "Operating periods in the fit",
  requested_start: "Requested training start",
  fit_start: "Actual fitting start",
  n_excluded_pre_maintenance: "Readings before latest maintenance",
  last_measurement_time: "Time of last reading",
  last_measurement: "Last reading",
  observed_threshold_exceedances: "Measured threshold crossings",
  latest_maintenance: "Latest maintenance event",
  observed_failure_time: "Observed failure time",
  variance_ratio_edge_probability: "Probability at the limits of the variance-ratio grid",
  training_span: "Time span of training observations",
  drift_confidence: "Drift interval level",
  parameter_draws: "Parameter draws",
  seed: "Forecast seed",
  reason: "Fit diagnostic",
};
const assumptionNames: Record<string, string> = {
  elapsed_time: "Forecasts use elapsed seconds and assume the fitted operating regime continues.",
  latest_maintenance: "The last restoration or replacement starts a fresh fitting segment. Measurements at the event are considered post-maintenance.",
  latent_threshold: "Failure is the first crossing of the engineering threshold by the underlying condition. A noisy reading can cross without confirming failure.",
  linear_model: "A linear trend extrapolates condition with uncertainty in the fitted parameters and zero future process variance.",
  stochastic_model: "Latent condition follows Brownian motion with constant drift. The model estimates measurement noise separately and samples continuous-time first passage.",
  one_event: "Expected cost covers one intervention or failure in the planning horizon and includes its full downtime.",
  retired_risk: "After intervention, the component contributes no further modeled failure cost within the horizon.",
  renewal_risk: "After intervention, the component contributes no further modeled failure cost within the horizon.",
  no_discount: "Costs are undiscounted over the planning horizon.",
  discount: "Costs are discounted continuously over the planning horizon.",
  failure_wins_ties: "Failure at the intervention time incurs corrective cost.",
  schedule_grid: "The comparison searches a regular 60-interval schedule grid and includes the selected schedule time.",
};
const chartColors = { observations: "#b5ed9a", fitted: "#83cbd6", forecast: "#c0adff", operating: "#8dbfcf", risk: "#e8aa88", cost: "#b5ed9a" };

function value(n: number | null) { return n == null ? "—" : number(n); }
function seconds(n: number | null) { return n == null ? "—" : tr("{0} s", { 0: number(n) }); }
function percent(n: number | null) { return n == null ? "—" : tr("{0}%", { 0: number(n * 100) }); }
function actionName(option: MaintenanceOption) {
  return tr(actionNames[option.action] || option.action);
}
function diagnosticValue(key: string, raw: Forecast["diagnostics"][string]) {
  if (raw == null) return "—";
  if (typeof raw === "number") return key.endsWith("_confidence") || key.endsWith("_probability") ? percent(raw) : value(raw);
  if (typeof raw === "string") {
    const minimum = raw.match(/^(\d+) finite readings are required for this model\.$/);
    return minimum ? tr("{0} finite readings are required for this model.", { 0: minimum[1] }) : tr(raw);
  }
  if (typeof raw === "boolean") return tr(raw ? "Yes" : "No");
  if (Array.isArray(raw)) {
    if (!raw.length) return "—";
    return raw.map(entry => Array.isArray(entry) ? entry.map(value).join(" – ") : value(entry)).join(Array.isArray(raw[0]) ? " · " : " – ");
  }
  return `${tr(raw.action === "restore" ? "Restoration" : "Replacement")} · ${seconds(raw.time)}`;
}
function Assumptions({ item }: { item: { assumptions: string[]; assumption_keys?: string[] } }) {
  return <ul className="pm-assumptions">{item.assumptions.map((description, index) => {
    const key = item.assumption_keys?.[index];
    return <li key={index}>{tr(key && assumptionNames[key] ? assumptionNames[key] : description)}</li>;
  })}</ul>;
}

function PrognosticCharts({ result, axis }: { result: FitResult; axis?: TimeAxis }) {
  const { config, forecast, maintenance } = result;
  const { history, trajectory, distribution, cutoff, horizon } = forecast;
  const [cursor, setCursor] = useState(0);
  const start = Math.min(history[0]?.time ?? cutoff, cutoff);
  const cursorTime = Math.min(cutoff + horizon, Math.max(start, cutoff + cursor));
  const elapsed = cursorTime - cutoff;
  const historyAxis: TimeAxis = axis || { kind: "numeric", start, end: cutoff + horizon, column: null, origin: null };
  const forecastAxis: TimeAxis = { kind: "numeric", start: 0, end: horizon, column: null, origin: null };
  const times = history.map(point => point.time);
  const future = trajectory.map(point => point.time);
  const conditionTimes = [...times, ...(times.at(-1) === cutoff ? [] : [cutoff]), ...future.filter(time => time > cutoff)];
  const conditionValues = [...history.map(point => point.value), ...conditionTimes.slice(times.length).map(() => null)];
  const operatingThreshold = config.indicator.operating_threshold;
  const operating = operatingThreshold == null ? [] : [{ times: [start, cutoff + horizon], values: [operatingThreshold, operatingThreshold], title: tr("Operational threshold"), color: chartColors.operating, dash: "3 5" }];
  const scheduled = maintenance.curve.filter((option): option is MaintenanceOption & { time: number } => option.time != null);
  const continueOption = maintenance.options.find(option => option.action === "continue");
  const selectableTimes = [...new Set([...conditionTimes, ...distribution.map(point => cutoff + point.time), ...scheduled.map(point => cutoff + point.time)])].sort((a, b) => a - b);
  const cursorIndex = selectableTimes.findIndex(time => time >= cursorTime);
  const chartDomain: [number, number] = [start, cutoff + horizon];
  const conditionTitle = tr("Measured condition ({0})", { 0: config.indicator.unit });
  const forecastTitle = tr("Median forecast");
  const bandTitle = tr("{0} prediction band", { 0: percent(forecast.rul.confidence) });
  const eventMarkers = (config.events ?? []).filter(event => event.time >= start && event.time <= cutoff)
    .map(event => ({ time: event.time, label: tr(event.action === "restore" ? "Restoration" : "Replacement"), annotation: true }));
  const loadSignal = result.source.loadSignal;
  const hasLoad = history.some(point => point.load != null);

  return <>
    {!!(times.length || future.length) && <section className="ws-panel pm-section" aria-labelledby="pm-condition">
      <h2 id="pm-condition">{tr("Condition and forecast")}</h2>
      <div className="pm-legend">
        {[[conditionTitle, chartColors.observations], [tr("Fitted condition"), chartColors.fitted],
          ...(future.length ? [[forecastTitle, chartColors.forecast], [bandTitle, chartColors.forecast]] : []),
          ...(operating.length ? [[tr("Operational threshold"), chartColors.operating]] : []),
          [tr("Failure threshold"), "#e2bc75"]].map(([label, color]) => <span key={label}><i style={{ backgroundColor: color }} />{label}</span>)}
      </div>
      <Plot
        times={conditionTimes} values={conditionValues} title={conditionTitle}
        axis={historyAxis} color={chartColors.observations} timeDomain={chartDomain}
        threshold={config.indicator.failure_threshold} thresholdLabel={tr("Failure threshold")}
        markers={[...eventMarkers, { time: cutoff, label: tr("Forecast cutoff"), annotation: true }]}
        selectedTime={cursorTime} onSelectTime={time => setCursor(time - cutoff)}
        overlays={[
          { times, values: history.map(point => point.fitted), title: tr("Fitted condition"), color: chartColors.fitted },
          { times: future, values: trajectory.map(point => point.median), title: forecastTitle, color: chartColors.forecast },
          ...operating,
        ]}
        band={future.length > 0 ? { times: future, lower: trajectory.map(point => point.lower), upper: trajectory.map(point => point.upper), title: bandTitle, color: chartColors.forecast } : undefined}
      />
      <label className="pm-cursor">{tr("Shared chart cursor")}
        <input type="range" min={0} max={Math.max(0, selectableTimes.length - 1)} step={1}
          value={cursorIndex === -1 ? selectableTimes.length - 1 : cursorIndex}
          onChange={event => setCursor(selectableTimes[Number(event.target.value)] - cutoff)}
          aria-valuetext={timeLabel(historyAxis, cursorTime)} />
      </label>
      <p className="pm-cursor-time"><output>{timeLabel(historyAxis, cursorTime)}</output> · {tr("{0} from cutoff", { 0: seconds(elapsed) })}</p>
      {hasLoad && <Plot times={times} values={history.map(point => point.load)} axis={historyAxis} timeDomain={chartDomain}
        title={loadSignal ? tr("Recorded operating load ({0})", { 0: loadSignal.unit || loadSignal.name }) : tr("Recorded operating load")}
        color={chartColors.fitted} selectedTime={cursorTime} onSelectTime={time => setCursor(time - cutoff)} />}
    </section>}
    {!!distribution.length && <section className="ws-panel pm-section" aria-labelledby="pm-risk">
      <h2 id="pm-risk">{tr("First-passage distribution")}</h2>
      <p>{tr("Cumulative probability of reaching the failure threshold by each time after the cutoff.")}</p>
      <Plot times={distribution.map(point => point.time)} values={distribution.map(point => 100 * point.probability)}
        axis={forecastAxis} timeDomain={[0, horizon]} domain={[0, 100]} title={tr("Cumulative failure probability (%)")}
        color={chartColors.risk} selectedTime={elapsed} onSelectTime={setCursor} />
    </section>}
    {!!scheduled.length && <section className="ws-panel pm-section" aria-labelledby="pm-intervention">
      <h2 id="pm-intervention">{tr("Cost by intervention time")}</h2>
      <Plot times={scheduled.map(option => option.time)} values={scheduled.map(option => option.expected_cost)}
        axis={forecastAxis} timeDomain={[0, horizon]} title={tr("Expected scheduled restoration cost")}
        selectedTime={elapsed <= maintenance.horizon ? elapsed : undefined} onSelectTime={setCursor} color={chartColors.cost}
        threshold={continueOption?.expected_cost} thresholdLabel={tr("Continue operating")} />
    </section>}
  </>;
}

export function PrognosticResults({ result, axis }: { result: FitResult; axis?: TimeAxis }) {
  const { forecast, maintenance } = result;
  const { rul } = forecast;
  const available = forecast.distribution.length > 0;
  const estimate = (bound: number | null) => bound == null && available
    ? tr("Beyond {0}", { 0: seconds(forecast.horizon) })
    : seconds(bound);
  const recommended = maintenance.recommended;
  const continueOption = maintenance.options.find(option => option.action === "continue");
  const savings = recommended && continueOption ? continueOption.expected_cost - recommended.expected_cost : 0;
  return <>
    <section className="ws-panel pm-section" aria-labelledby="pm-rul">
      <div className="pm-heading"><h2 id="pm-rul">{tr("Remaining useful life")}</h2><span className="ws-badge">{modelName(forecast.method)} · {forecast.model_version}</span></div>
      <p>{result.config.assetName} · {result.source.datasetName || result.config.datasetId} · {result.config.indicator.signal} ({result.config.indicator.unit})</p>
      <p role="status">{forecastStatus(forecast.status)}</p>
      <dl className="pm-metrics">
        <div><dt>{tr("Median time to failure threshold")}</dt><dd>{estimate(rul.median)}</dd></div>
        <div><dt>{tr("{0} first-passage interval", { 0: percent(rul.confidence) })}</dt><dd>{available ? `${estimate(rul.lower)} – ${estimate(rul.upper)}` : "—"}</dd></div>
        {rul.probabilities.map(point => <div key={point.horizon}><dt>{tr("Failure within {0}", { 0: seconds(point.horizon) })}</dt><dd>{percent(point.probability)}</dd></div>)}
        {rul.probability_not_reached_by_horizon != null && <div><dt>{tr("No crossing by the forecast horizon")}</dt><dd>{percent(rul.probability_not_reached_by_horizon)}</dd></div>}
      </dl>
      <details><summary>{tr("Model assumptions and diagnostics")}</summary>
        <Assumptions item={forecast} />
        {rul.probability_never_reached_under_model != null && <p>{tr("Under this model, {0} of paths never cross. This is included in the no-crossing probability at the forecast horizon.", { 0: percent(rul.probability_never_reached_under_model) })}</p>}
        <dl className="pm-diagnostics">{Object.entries(forecast.diagnostics).map(([key, raw]) => <div key={key}>
          <dt>{tr(diagnosticNames[key] || key.replaceAll("_", " "))}</dt><dd>{diagnosticValue(key, raw)}</dd>
        </div>)}</dl>
      </details>
    </section>
    <PrognosticCharts key={forecast.cutoff} result={result} axis={axis} />
    <section className="ws-panel pm-section" aria-labelledby="pm-costs">
      <h2 id="pm-costs">{tr("Maintenance strategies")}</h2>
      <p>{tr("Planning horizon · {0} after cutoff", { 0: seconds(maintenance.horizon) })}</p>
      {recommended ? <p className="ws-notice">
        <strong>{recommended.time != null && recommended.time > 0 ? tr("{0} at {1}", { 0: actionName(recommended), 1: seconds(recommended.time) }) : actionName(recommended)}.</strong>{" "}
        {tr(maintenance.status === "threshold_reached"
          ? "Confirmed failure incurs corrective cost ({0})."
          : "This option has the lowest expected cost among the evaluated strategies ({0}).", { 0: number(recommended.expected_cost) })}
        {savings > 0 ? " " + tr("Expected savings versus continuing are {0}.", { 0: number(savings) }) : ""}
      </p> : <p>{tr("A usable first-passage distribution is required for a maintenance comparison.")}</p>}
      {!!maintenance.options.length && <div className="ws-table-scroll"><table>
        <thead><tr><th>{tr("Strategy")}</th><th>{tr("Time after cutoff")}</th><th>{tr("Failure probability by intervention")}</th><th>{tr("Expected failure cost")}</th><th>{tr("Expected planned intervention cost")}</th><th>{tr("Expected total cost")}</th></tr></thead>
        <tbody>{maintenance.options.map(option => <tr key={`${option.action}-${option.time}`}>
          <td>{actionName(option)}</td><td>{option.time == null ? tr("Through horizon") : seconds(option.time)}</td>
          <td>{percent(option.failure_probability)}</td><td>{value(option.expected_failure_cost)}</td>
          <td>{value(option.expected_intervention_cost)}</td><td>{value(option.expected_cost)}</td>
        </tr>)}</tbody>
      </table></div>}
      <details><summary>{tr("Cost model assumptions")}</summary><Assumptions item={maintenance} /></details>
    </section>
  </>;
}

function ReliabilityTable({ metrics }: { metrics: EvaluationGroup["reliability"] }) {
  return <div className="ws-table-scroll"><table>
    <thead><tr><th>{tr("Horizon")}</th><th>{tr("Known outcomes")}</th><th>{tr("Brier score")}</th><th>{tr("Mean forecast probability")}</th><th>{tr("Observed failure rate")}</th></tr></thead>
    <tbody>{metrics.map(metric => <tr key={metric.horizon}><td>{seconds(metric.horizon)}</td><td>{metric.count}</td><td>{value(metric.brier)}</td><td>{percent(metric.predicted)}</td><td>{percent(metric.observed)}</td></tr>)}</tbody>
  </table></div>;
}

function CalibrationTable({ metrics }: { metrics: EvaluationGroup["reliability"] }) {
  return <details><summary>{tr("Probability calibration by forecast bin")}</summary>
    <div className="ws-table-scroll"><table>
      <thead><tr><th>{tr("Horizon")}</th><th>{tr("Forecast probability bin")}</th><th>{tr("Known outcomes")}</th><th>{tr("Mean forecast probability")}</th><th>{tr("Observed failure rate")}</th></tr></thead>
      <tbody>{metrics.flatMap(metric => metric.bins.map(bin => <tr key={`${metric.horizon}-${bin.lower}`}>
        <td>{seconds(metric.horizon)}</td><td>{percent(bin.lower)} – {percent(bin.upper)}</td>
        <td>{bin.count}</td><td>{percent(bin.predicted)}</td><td>{percent(bin.observed)}</td>
      </tr>))}</tbody>
    </table></div>
  </details>;
}

export function PrognosticEvaluation({ evaluation }: { evaluation: Evaluation }) {
  const { protocol, trajectories, models } = evaluation;
  return <div className="pm-evaluation">
    <p>{tr("Protocol {0} · {1} held-out trajectories · evaluation seeds {2}", { 0: protocol.id, 1: trajectories.length, 2: protocol.evaluation_seeds.join(", ") })}</p>
    <p>{tr("A censored history contributes to a horizon score only when the outcome is known. RUL error uses observed failures with a finite forecast median.")}</p>
    <p>{tr("Development seed {0} · cutoff times {1} · planning horizon {2}", {
      0: protocol.development_seed, 1: protocol.cutoffs.map(seconds).join(", "), 2: seconds(protocol.planning_horizon),
    })}</p>
    <div className="ws-table-scroll"><table>
      <thead><tr><th>{tr("Model")}</th><th>{tr("Finite medians / observed failures")}</th><th>{tr("RUL MAE (s)")}</th><th>{tr("RUL bias (s)")}</th><th>{tr("Interval coverage")}</th><th>{tr("Mean absolute failure-time revision (s)")}</th></tr></thead>
      <tbody>{models.map(model => <tr key={model.method}>
        <td>{modelName(model.method)}</td><td>{model.rul.median_available} / {model.rul.count}</td>
        <td>{value(model.rul.mae)}</td><td>{value(model.rul.bias)}</td>
        <td>{percent(model.rul.coverage)} ({model.rul.interval_count})</td><td>{value(model.stability.mean_absolute_revision)}</td>
      </tr>)}</tbody>
    </table></div>
    {models.map(model => <details key={model.method}>
      <summary>{tr("{0} · reliability, costs and scenario results", { 0: modelName(model.method) })}</summary>
      <ReliabilityTable metrics={model.reliability} />
      <CalibrationTable metrics={model.reliability} />
      <h3>{tr("Observed maintenance cost on known planning outcomes")}</h3>
      <dl className="pm-metrics">
        <div><dt>{tr("Recommended policy")}</dt><dd>{value(model.maintenance.policy)}</dd></div>
        <div><dt>{tr("Continue operating")}</dt><dd>{value(model.maintenance.continue)}</dd></div>
        <div><dt>{tr("Restore now")}</dt><dd>{value(model.maintenance.immediate)}</dd></div>
        <div><dt>{tr("Restore at midpoint")}</dt><dd>{value(model.maintenance.fixed_midpoint)}</dd></div>
        <div><dt>{tr("Known outcomes")}</dt><dd>{model.maintenance.count}</dd></div>
      </dl>
      <h3>{tr("Fit outcomes")}</h3>
      <ul className="pm-assumptions">{Object.entries(model.statuses).map(([status, count]) => <li key={status}>{forecastStatus(status as ForecastStatus)} ({count})</li>)}</ul>
      <div className="ws-table-scroll"><table>
        <thead><tr><th>{tr("Scenario")}</th><th>{tr("Cases")}</th><th>{tr("RUL MAE (s)")}</th><th>{tr("Interval coverage")}</th><th>{tr("Mean absolute failure-time revision (s)")}</th><th>{tr("Recommended policy cost")}</th></tr></thead>
        <tbody>{model.by_scenario.map(scenario => <tr key={scenario.scenario}>
          <td>{tr(scenario.scenario)}</td><td>{scenario.case_count}</td><td>{value(scenario.rul.mae)}</td>
          <td>{percent(scenario.rul.coverage)}</td><td>{value(scenario.stability.mean_absolute_revision)}</td><td>{value(scenario.maintenance.policy)}</td>
        </tr>)}</tbody>
      </table></div>
    </details>)}
  </div>;
}
