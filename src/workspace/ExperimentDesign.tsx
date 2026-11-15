import { useEffect, useRef, useState, type FormEvent } from "react";
import { t, useLocale } from "../i18n";
import { downloadFile } from "../lib/download";
import { api, go, message } from "./api";
import { Plot } from "./Charts";
import type { Dataset, TimeAxis } from "./types";
import "./experimentDesign.css";

type Pair = [number, number];
type Coefficients = Record<string, number>;
type Config = {
  modelId: string; duration: number; controlInterval: number; segments: number;
  sampleInterval: number; integrationStep: number; seed: number; objective: "D" | "E";
  initialLevels: Pair; levelMin: Pair; levelMax: Pair; tankHeight: number; minDelivery: number;
  terminalLevelTolerance: number | null; initialInput: Pair; terminalInput: Pair | null;
  inputMin: Pair; inputMax: Pair; maxSlew: Pair; maxMovement: Pair;
  parameters: string[]; noise: Record<string, number>; nominal: Coefficients; scenarios: Coefficients[];
};
type Catalog = {
  defaults: Config; experiments: SavedSummary[];
  measurements: Record<string, { label: string; unit: string }>;
  parameters: Record<string, { label: string; unit: string; min: number; max: number }>;
};
type ScheduleRow = { start: number; pump: number; valve: number };
type Report = {
  parameters: Coefficients; objective: number; rank: number; singularValues: number[];
  eigenvalues: number[]; logDet: number | null; condition: number | null; matrix: number[][];
  physicalMatrix: number[][]; correlation: number[][] | null; weakDirections: number[][];
  rankThreshold: number; differenceDisagreement: number; sensitivity: number[][][];
  structurallyAbsent: string[]; times: number[]; response: Record<string, number[]>;
  observations: Record<string, number[]>; sampledInputs: Record<string, number[]>;
  feasible: boolean; margins: Record<string, number[]>; delivered: number; spilled: number;
  massResidual: number; extrema: { minAt: Pair; maxAt: Pair; substeps: number };
};
type Strategy = {
  id: string; schedule: ScheduleRow[]; duration: number; movement: Pair; maxSlew: Pair;
  inputMargins: Record<string, number[]>; inputFeasible: boolean; feasible: boolean;
  reports: Record<string, Report>; violatedScenarios: string[]; worstScenario: string; worstObjective: number;
};
type Solver = {
  success: boolean; status: number | null; message: string; iterations: number | null;
  functionEvaluations: number | null; candidateEvaluations: number; candidateBudget: number;
  elapsedSeconds: number; solverObjective: number; solverMinMargin: number; auditedStatus: string;
  selected: string; auditedObjective: number;
};
type SavedSummary = { id: string; name: string; status: string; created_at: string };
type Saved = SavedSummary & { snapshot: {
  config: Config; designs: Strategy[]; solvers: Record<string, Solver>;
  diagnostics: { dRidge: number; stateIntegrationStep: number; feasibilityTolerance: number };
} };

const strategies: Record<string, string> = {
  constant: "Constant / endpoint reference", step: "Single step", multistep: "Multiple steps",
  prbs: "PRBS", "nominal-optimal": "Nominal optimization", "robust-optimal": "Worst-case optimization",
  solver: "Solver candidate",
};
const fmt = (n: number | null) => n === null ? "—" : Number(n.toPrecision(5)).toString();
const scenarioName = (id: string) => id === "nominal" ? t("Nominal") : t("Scenario {n}", { n: id.split("-")[1] });
const csv = (rows: (string | number)[][]) => rows.map(row => row.join(",")).join("\n") + "\n";
const visibility = (feasible: boolean) => feasible ? "ws-accent" : "ws-coral";
const fieldLabels: Record<string, string> = {
  duration: "Duration (s)", controlInterval: "Control update interval (s)", segments: "Number of control segments",
  sampleInterval: "Observation interval (s)", integrationStep: "Maximum integration step (s)", seed: "Random seed",
  initialLevels: "Initial levels", levelMin: "Minimum levels", levelMax: "Maximum levels", initialInput: "Initial control segment",
  terminalInput: "Final control segment", inputMin: "Lower actuator bounds", inputMax: "Upper actuator bounds",
  maxSlew: "Maximum slew per update", maxMovement: "Maximum cumulative movement", tankHeight: "Overflow height",
  minDelivery: "Minimum delivered volume (m³)", terminalLevelTolerance: "Terminal level tolerance",
};

function designError(error: string, catalog: Catalog | null) {
  const [key] = error.split(":");
  const field = t(fieldLabels[key] ?? catalog?.parameters[key]?.label ?? catalog?.measurements[key]?.label ?? key);
  const range = error.match(/: expected (a number|an integer) in (\[[^\]]+\])\.$/);
  if (range) return t(range[1] === "an integer" ? "{field} must be an integer in {range}." : "{field} must be in {range}.", { field, range: range[2] });
  if (error.endsWith(": expected two numbers.")) return t("Enter two values for {field}.", { field });
  return t(error);
}

function Numeric({ label, value, update, min, max, step = "any" }: {
  label: string; value: number; update: (n: number) => void;
  min?: number; max?: number; step?: number | "any";
}) {
  return <label>{label}<input type="number" required min={min} max={max} step={step}
    value={Number.isNaN(value) ? "" : value} onChange={e => update(e.currentTarget.valueAsNumber)} /></label>;
}

function PairFields({ title, value, update, units, labels }: {
  title: string; value: Pair; update: (pair: Pair) => void; units: PairUnits; labels: PairLabels;
}) {
  return <fieldset className="oed-pair"><legend>{title}</legend>
    <div className="oed-fields">{value.map((v, i) => <Numeric key={i} label={`${labels[i]} (${units[i]})`}
      value={v} min={0} update={n => update(i === 0 ? [n, value[1]] : [value[0], n])} />)}</div>
  </fieldset>;
}
type PairUnits = [string, string];
type PairLabels = [string, string];

function DesignForm({ catalog, config, setConfig, name, setName, saving, generate }: {
  catalog: Catalog; config: Config; setConfig: (c: Config) => void; name: string;
  setName: (name: string) => void; saving: boolean; generate: (e: FormEvent) => void;
}) {
  const set = <K extends keyof Config>(key: K, value: Config[K]) => setConfig({ ...config, [key]: value });
  const inputs: PairLabels = [t("Pump"), t("Connection valve")];
  const levels: PairLabels = [t("Tank 1"), t("Tank 2")];
  const clocks = [
    ["duration", 1, 600, "any"], ["controlInterval", .1, 600, "any"], ["segments", 1, 12, 1],
    ["sampleInterval", .1, 600, "any"], ["integrationStep", .025, .25, "any"], ["seed", 0, 2147483647, 1],
  ] as const;
  const parameterFields = (values: Coefficients, update: (v: Coefficients) => void) =>
    Object.entries(catalog.parameters).map(([key, field]) => <Numeric key={key}
      label={`${t(field.label)} (${field.unit})`} value={values[key]} min={Math.max(1e-4, field.min)}
      max={field.max} update={n => update({ ...values, [key]: n })} />);

  return <form className="ws-panel oed-form" onSubmit={generate}>
    <fieldset disabled={saving}>
      <legend>{t("Experiment definition")}</legend>
      <div className="oed-fields">
        <label>{t("Experiment name")}<input required maxLength={160} value={name} onChange={e => setName(e.target.value)} /></label>
        <label>{t("Process model")}<select value={config.modelId} onChange={e => set("modelId", e.target.value)}>
          <option value="coupled-tanks">{t("Coupled-Tank Process")}</option>
        </select></label>
        <label>{t("Information objective")}<select value={config.objective} onChange={e => set("objective", e.target.value === "D" ? "D" : "E")}>
          <option value="D">{t("D-optimality · log determinant")}</option>
          <option value="E">{t("E-optimality · smallest eigenvalue")}</option>
        </select></label>
        {clocks.map(([key, min, max, step]) => <Numeric key={key} label={t(fieldLabels[key])} value={config[key]}
          min={min} max={max} step={step} update={v => set(key, v)} />)}
      </div>
      <p className="ws-muted">{t("Segment starts are spaced by the control update interval. The final segment holds until the experiment ends.")}</p>
      <details open>
        <summary>{t("Parameters and observations")}</summary>
        <div className="oed-fields">
          {Object.entries(catalog.parameters).map(([key, field]) => <label key={key} className="oed-check">
            <input type="checkbox" checked={config.parameters.includes(key)} onChange={e =>
              set("parameters", e.target.checked ? [...config.parameters, key] : config.parameters.filter(p => p !== key))} />
            {t(field.label)}
          </label>)}
        </div>
        <div className="oed-fields">{Object.entries(catalog.measurements).map(([key, field]) =>
          <div key={key} className="oed-observation">
            <label className="oed-check"><input type="checkbox" checked={Object.hasOwn(config.noise, key)}
              onChange={e => {
                const next = { ...config.noise };
                if (e.target.checked) next[key] = catalog.defaults.noise[key] ?? .002;
                else delete next[key];
                set("noise", next);
              }} />{t(field.label)}</label>
            {Object.hasOwn(config.noise, key) && <Numeric label={t("Noise σ for {signal} ({unit})", { signal: t(field.label), unit: field.unit })}
              value={config.noise[key]} min={1e-6} max={1} update={n => set("noise", { ...config.noise, [key]: n })} />}
          </div>)}</div>
        <p className="ws-muted">{t("Noise is additive Gaussian, independent across channels and samples.")}</p>
      </details>
      <details>
        <summary>{t("Operating conditions and limits")}</summary>
        <div className="oed-pairs">
          <PairFields title={t("Initial levels")} value={config.initialLevels} update={v => set("initialLevels", v)} units={["m", "m"]} labels={levels} />
          <PairFields title={t("Minimum levels")} value={config.levelMin} update={v => set("levelMin", v)} units={["m", "m"]} labels={levels} />
          <PairFields title={t("Maximum levels")} value={config.levelMax} update={v => set("levelMax", v)} units={["m", "m"]} labels={levels} />
          <PairFields title={t("Initial control segment")} value={config.initialInput} update={v => set("initialInput", v)} units={["%", "0–1"]} labels={inputs} />
          <PairFields title={t("Lower actuator bounds")} value={config.inputMin} update={v => set("inputMin", v)} units={["%", "0–1"]} labels={inputs} />
          <PairFields title={t("Upper actuator bounds")} value={config.inputMax} update={v => set("inputMax", v)} units={["%", "0–1"]} labels={inputs} />
          <PairFields title={t("Maximum slew per update")} value={config.maxSlew} update={v => set("maxSlew", v)} units={["%/s", "1/s"]} labels={inputs} />
          <PairFields title={t("Maximum cumulative movement")} value={config.maxMovement} update={v => set("maxMovement", v)} units={["%", "0–1"]} labels={inputs} />
        </div>
        <div className="oed-fields">
          <Numeric label={t("Overflow height (m)")} value={config.tankHeight} min={.1} max={10} update={n => set("tankHeight", n)} />
          <Numeric label={t("Minimum delivered volume (m³)")} value={config.minDelivery} min={0} max={120} update={n => set("minDelivery", n)} />
        </div>
        <label className="oed-check"><input type="checkbox" checked={config.terminalInput !== null}
          onChange={e => set("terminalInput", e.target.checked ? [...config.initialInput] : null)} />{t("Fix final control segment")}</label>
        {config.terminalInput && <PairFields title={t("Final control segment")} value={config.terminalInput}
          update={v => set("terminalInput", v)} units={["%", "0–1"]} labels={inputs} />}
        <label className="oed-check"><input type="checkbox" checked={config.terminalLevelTolerance !== null}
          onChange={e => set("terminalLevelTolerance", e.target.checked ? .1 : null)} />{t("Return levels toward the initial state")}</label>
        {config.terminalLevelTolerance !== null && <div className="oed-fields"><Numeric label={t("Terminal level tolerance (m)")} value={config.terminalLevelTolerance}
          min={0} max={10} update={n => set("terminalLevelTolerance", n)} /></div>}
      </details>
      <details>
        <summary>{t("Nominal and robust parameter configurations")}</summary>
        <h3>{t("Nominal")}</h3>
        <div className="oed-fields">{parameterFields(config.nominal, v => set("nominal", v))}</div>
        {config.scenarios.map((item, i) => <fieldset key={i} className="oed-pair">
          <legend>{scenarioName(`scenario-${i+1}`)}</legend>
          <div className="oed-fields">{parameterFields(item, v => set("scenarios", config.scenarios.map((p, j) => j === i ? v : p)))}</div>
          <button type="button" className="ws-outlined" onClick={() => set("scenarios", config.scenarios.filter((_, j) => j !== i))}>{t("Remove configuration")}</button>
        </fieldset>)}
        <button type="button" className="ws-outlined" disabled={config.scenarios.length >= 4}
          onClick={() => set("scenarios", [...config.scenarios, { ...config.nominal }])}>{t("Add parameter configuration")}</button>
      </details>
      <button className="ws-primary" disabled={!name.trim() || !config.parameters.length || !Object.keys(config.noise).length}>
        {saving ? t("Evaluating schedules…") : t("Generate and save experiment")}
      </button>
    </fieldset>
  </form>;
}

function Matrix({ label, values, names }: { label: string; values: number[][]; names: string[] }) {
  return <div className="ws-table-scroll"><table>
    <caption>{label}</caption>
    <thead><tr><th scope="col">{t("Parameter")}</th>{names.map(n => <th scope="col" key={n}>{n}</th>)}</tr></thead>
    <tbody>{values.map((row, i) => <tr key={i}><th scope="row">{names[i]}</th>
      {row.map((v, j) => <td key={j}>{fmt(v)}</td>)}</tr>)}</tbody>
  </table></div>;
}

const marginNames: Record<string, string> = {
  inputLower: "Lower actuator bounds", inputUpper: "Upper actuator bounds", slew: "Slew", movement: "Cumulative movement",
  initialInput: "Initial control segment", terminalInput: "Final control segment", levelLower: "Minimum levels",
  levelUpper: "Maximum levels", overflow: "Overflow height", delivery: "Delivered volume", terminalLevel: "Terminal level tolerance",
};

function ConstraintTable({ strategy, report, interval }: { strategy: Strategy; report: Report; interval: number }) {
  const rows = [
    ...Object.entries(strategy.inputMargins).map(([key, values]) => {
      const divisor = key === "slew" ? interval : 1;
      return [key, [values[0]*100/divisor, values[1]/divisor], key === "slew" ? "%/s · 1/s" : "% · 0–1"] as const;
    }),
    ...Object.entries(report.margins).map(([key, values]) => [key, values, key === "delivery" ? "m³" : "m"] as const),
  ];
  return <div className="ws-table-scroll"><table>
    <thead><tr><th>{t("Hard constraint")}</th><th>{t("Margins")}</th><th>{t("Units")}</th></tr></thead>
    <tbody>{rows.map(([key, values, unit]) => <tr key={key}><th scope="row">{t(marginNames[key])}</th>
      <td>{values.map(fmt).join(" / ")}</td><td>{unit}</td></tr>)}</tbody>
  </table></div>;
}

function Results({ record, catalog, workspaceId, onPublished }: {
  record: Saved; catalog: Catalog; workspaceId: string; onPublished: () => void;
}) {
  const { config, designs, solvers, diagnostics } = record.snapshot;
  const [strategyId, setStrategy] = useState(designs.at(-1)?.id ?? "");
  const [scenario, setScenario] = useState("nominal");
  const [sensor, setSensor] = useState(Object.keys(config.noise)[0]);
  const [publishing, setPublishing] = useState(false);
  const [published, setPublished] = useState<Dataset | null>(null);
  const [error, setError] = useState("");
  const pick = designs.find(d => d.id === strategyId);
  if (!pick) return <section className="ws-panel"><h2>{t("Actuator constraints are infeasible")}</h2>
    <p>{t("Check that both fixed commands are inside the bounds and reachable under the slew and movement limits.")}</p></section>;
  const report = pick.reports[scenario], scenarios = Object.keys(pick.reports);
  const selectionFeasible = pick.inputFeasible && report.feasible;
  const axis: TimeAxis = { kind: "numeric", column: "time", origin: null, start: 0, end: config.duration };
  const paramNames = config.parameters.map(p => t(catalog.parameters[p].label));
  const colors = ["#8cbfe8", "#e2bc75"];
  const switches = pick.schedule.flatMap((s, i) => [s.start, pick.schedule[i+1]?.start ?? config.duration]);
  const file = `${pick.id}-${scenario}`;
  const resetPublish = () => { setError(""); setPublished(null); };

  async function publish() {
    setPublishing(true); resetPublish();
    try {
      const data = await api<Dataset>(`/workspaces/${workspaceId}/experiment-designs/${record.id}/datasets`,
        { designId: pick!.id, scenarioId: scenario });
      setPublished(data);
      onPublished();
    } catch (e) { setError(message(e)); }
    finally { setPublishing(false); }
  }

  function exportObservations() {
    const columns = { ...report.sampledInputs, ...report.observations };
    downloadFile(`${file}-observations.csv`, csv([["time", ...Object.keys(columns)],
      ...report.times.map((time, i) => [time, ...Object.values(columns).map(series => series[i])])]), "text/csv");
  }

  return <>
    <section className="ws-panel oed-results">
      <h2>{t("Compare excitation strategies")}</h2>
      <p className="ws-muted">{t("All strategies use the same horizon, observation grid and input limits. Feasibility includes every listed configuration.")}</p>
      <div className="ws-table-scroll"><table>
        <thead><tr><th>{t("Strategy")}</th><th>{t("Nominal score")}</th><th>{t("Worst-case score")}</th>
          <th>{t("Weakest configuration")}</th><th>{t("Worst rank")}</th><th>{t("Pump / valve movement")}</th><th>{t("Violations")}</th></tr></thead>
        <tbody>{designs.map(d => <tr key={d.id}>
          <th scope="row"><button type="button" className="ws-link" disabled={publishing} aria-pressed={pick.id === d.id}
            onClick={() => { setStrategy(d.id); resetPublish(); }}>{t(strategies[d.id])}</button></th>
          <td>{fmt(d.reports.nominal.objective)}</td><td>{fmt(d.worstObjective)}</td><td>{scenarioName(d.worstScenario)}</td>
          <td>{Math.min(...Object.values(d.reports).map(s => s.rank))}/{config.parameters.length}</td>
          <td>{fmt(d.movement[0])}% / {fmt(d.movement[1])}</td>
          <td className={visibility(d.feasible)}>{[!d.inputFeasible && t("Actuators"), ...d.violatedScenarios.map(scenarioName)].filter(Boolean).join(", ") || t("None")}</td>
        </tr>)}</tbody>
      </table></div>
      <details>
        <summary>{t("Solver diagnostics")}</summary>
        <p className="ws-muted">{t("SLSQP uses a local search. The saved schedule is the best evaluated candidate that passed its design constraints, when one exists.")}</p>
        <div className="ws-table-scroll"><table>
          <thead><tr><th>{t("Strategy")}</th><th>{t("Solver status")}</th><th>{t("Retained schedule")}</th>
            <th>{t("Solver score / audited score")}</th><th>{t("Solver minimum residual")}</th><th>{t("Model evaluations / limit")}</th><th>{t("Elapsed time (s)")}</th></tr></thead>
          <tbody>{Object.entries(solvers).map(([key, s]) => <tr key={key}><th scope="row">{t(strategies[key])}</th>
            <td className={visibility(s.success)}>{t(s.message)}{s.status === null ? "" : ` (${s.status})`}</td>
            <td>{t(strategies[s.selected])} · {t(s.auditedStatus)}</td><td>{fmt(s.solverObjective)} / {fmt(s.auditedObjective)}</td>
            <td>{fmt(s.solverMinMargin)}</td><td>{s.candidateEvaluations} / {s.candidateBudget}</td><td>{fmt(s.elapsedSeconds)}</td></tr>)}</tbody>
        </table></div>
      </details>
    </section>
    <section className="ws-panel oed-results">
      <h2>{t(strategies[pick.id])}</h2>
      <div className="oed-fields">
        <label>{t("Inspect parameter configuration")}<select value={scenario} disabled={publishing}
          onChange={e => { setScenario(e.target.value); resetPublish(); }}>
          {scenarios.map(k => <option value={k} key={k}>{scenarioName(k)}</option>)}
        </select></label>
        <span className={visibility(selectionFeasible)} role="status">{selectionFeasible ? t("Passes simulated constraints") : t("Violates simulated constraints")}</span>
      </div>
      <p className="ws-muted">{Object.entries(report.parameters).map(([key, value]) =>
        `${t(catalog.parameters[key].label)} ${fmt(value)} ${catalog.parameters[key].unit}`).join(" · ")}</p>
      <div className="oed-plots">
        {(["pump", "valve"] as const).map(key => <Plot key={key} axis={axis} times={switches}
          values={pick.schedule.flatMap(s => [s[key], s[key]])} title={t(key === "pump" ? "Pump command (%)" : "Connection valve opening (fraction)")} />)}
        {(["level1", "level2"] as const).map((key, i) => <Plot key={key} axis={axis} times={report.times}
          values={report.response[key]} title={`${t(catalog.measurements[key].label)} (m)`}
          threshold={Math.min(config.levelMax[i], config.tankHeight)} thresholdLabel={t("Upper limit")} />)}
      </div>
      <details open>
        <summary>{t("Information and sensitivity")}</summary>
        <p className="ws-muted">{config.objective === "D" ?
          t("D scores use a diagonal ridge of {ridge}. Rank, log determinant, condition and correlation use unregularized information.", { ridge: diagnostics.dRidge }) :
          t("E scores use the smallest unregularized information eigenvalue.")}</p>
        {report.rank < config.parameters.length && <p className="ws-notice">{t("The sensitivity is rank deficient at the reported numerical resolution. These data do not identify all selected parameters independently.")}</p>}
        {!!report.structurallyAbsent.length && <p className="ws-notice">{t("With inlet flow as the only measurement, these coefficients do not affect the output under any input schedule")}
          {" · "}{report.structurallyAbsent.map(k => t(catalog.parameters[k].label)).join(", ")}</p>}
        <dl className="oed-metrics">
          <div><dt>{t("Rank")}</dt><dd>{report.rank}/{config.parameters.length}</dd></div>
          <div><dt>{t("Unregularized log determinant")}</dt><dd>{fmt(report.logDet)}</dd></div>
          <div><dt>{t("Information condition number")}</dt><dd>{fmt(report.condition)}</dd></div>
          <div><dt>{t("Whitened singular values")}</dt><dd>{report.singularValues.map(fmt).join(" / ")}</dd></div>
          <div><dt>{t("Information eigenvalues")}</dt><dd>{report.eigenvalues.map(fmt).join(" / ")}</dd></div>
          <div><dt>{t("Rank cutoff / derivative disagreement")}</dt><dd>{fmt(report.rankThreshold)} / {fmt(report.differenceDisagreement)}</dd></div>
        </dl>
        <Matrix label={t("Fisher information (nominal-scaled coefficients)")} names={paramNames} values={report.matrix} />
        <details><summary>{t("Physical-coordinate information and correlations")}</summary>
          <Matrix label={t("Fisher information in physical units")} names={paramNames} values={report.physicalMatrix} />
          {report.correlation ? <Matrix label={t("Local parameter correlation estimate")} names={paramNames} values={report.correlation} />
            : <p>{t("Correlation is unavailable at the reported rank.")}</p>}
        </details>
        <p>{t("Weak directions in nominal-scaled coefficients")}</p>
        <ul>{report.weakDirections.map((row, i) => <li key={i}>
          {row.map((v, j) => `${fmt(v)} × ${paramNames[j]}`).join(" · ")}</li>)}</ul>
        <label>{t("Sensitivity and observation channel")}<select value={sensor} onChange={e => setSensor(e.target.value)}>
          {Object.keys(config.noise).map(key => <option key={key} value={key}>{t(catalog.measurements[key].label)}</option>)}
        </select></label>
        <Plot axis={axis} times={report.times} values={report.observations[sensor]}
          title={t("Simulated observations ({unit})", { unit: catalog.measurements[sensor].unit })}
          overlays={[{ times: report.times, values: report.response[sensor], title: t("Physical response"), color: colors[0] }]} />
        {paramNames.map((parameter, i) => <Plot key={parameter} axis={axis} times={report.times}
          values={report.sensitivity.map(row => row[Object.keys(config.noise).indexOf(sensor)][i])}
          title={`${parameter} · ${t("Scaled sensitivity")} (${catalog.measurements[sensor].unit})`} color={colors[i % colors.length]} />)}
      </details>
      <details>
        <summary>{t("Constraint margins and hydraulic checks")}</summary>
        <p className="ws-muted">{t("Levels and overflow are checked at {n} integration substeps with a maximum step of {step} s. The feasibility tolerance is {tol}.",
          { n: report.extrema.substeps, step: diagnostics.stateIntegrationStep, tol: diagnostics.feasibilityTolerance })}</p>
        <ConstraintTable strategy={pick} report={report} interval={config.controlInterval} />
        <dl className="oed-metrics">
          <div><dt>{t("Delivered volume")} (m³)</dt><dd>{fmt(report.delivered)}</dd></div>
          <div><dt>{t("Spilled volume")} (m³)</dt><dd>{fmt(report.spilled)}</dd></div>
          <div><dt>{t("Maximum mass residual")} (m³)</dt><dd>{fmt(report.massResidual)}</dd></div>
          <div><dt>{t("Time of peak levels")} (s)</dt><dd>{report.extrema.maxAt.map(fmt).join(" / ")}</dd></div>
        </dl>
      </details>
      <div className="oed-actions">
        <button className="ws-outlined" onClick={() => downloadFile(`${pick.id}-schedule.csv`, csv([["start_s", "end_s", "pump_percent", "valve_fraction"],
          ...pick.schedule.map((row, i) => [row.start, pick.schedule[i+1]?.start ?? config.duration, row.pump, row.valve])]), "text/csv")}>{t("Download schedule CSV")}</button>
        <button className="ws-outlined" onClick={exportObservations}>{t("Download observations CSV")}</button>
        <button className="ws-primary" disabled={publishing} onClick={publish}>{publishing ? t("Publishing…") : t("Publish as Dataset")}</button>
      </div>
      {published && <p role="status"><a className="ws-link" href={`#/workspaces/${workspaceId}/datasets/${published.id}`}>{t("Open published Dataset")} ↗</a></p>}
      {error && <p className="ws-error" role="alert">{t(error)}</p>}
    </section>
  </>;
}

export function ExperimentDesign({ workspaceId, experimentId, onPublished }: {
  workspaceId: string; experimentId?: string; onPublished: () => void;
}) {
  useLocale();
  const base = `/workspaces/${workspaceId}/experiment-designs`;
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [record, setRecord] = useState<Saved | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [name, setName] = useState(t("Tank excitation experiment"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const saveRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api<Catalog>(base, undefined, "GET", controller.signal),
      experimentId ? api<Saved>(`${base}/${experimentId}`, undefined, "GET", controller.signal) : Promise.resolve(null),
    ]).then(([data, saved]) => {
      if (controller.signal.aborted) return;
      setCatalog(data); setRecord(saved); setConfig(saved?.snapshot.config ?? data.defaults);
      if (saved) setName(saved.name);
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => { controller.abort(); saveRequest.current?.abort(); };
  }, [base, experimentId]);

  async function generate(e: FormEvent) {
    e.preventDefault();
    const controller = new AbortController();
    saveRequest.current = controller;
    setBusy(true); setError("");
    try {
      const saved = await api<Saved>(base, { name, config }, "POST", controller.signal);
      if (!controller.signal.aborted) go(`workspaces/${workspaceId}/experiment-designs/${saved.id}`);
    } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }

  return <>
    <div className="ws-page-title"><div><h1>{t("Optimal Experiment Design")}</h1>
      <p>{t("Plan bounded pump and valve excitation for parameter identification in a simulated coupled-tank process.")}</p></div></div>
    <div className="ws-panel oed-library">
      <label>{t("Saved input designs")}<select value={experimentId ?? ""} disabled={busy || !catalog} onChange={e => {
        const id = e.target.value;
        go(`workspaces/${workspaceId}/experiment-designs${id ? `/${id}` : ""}`);
      }}>
        <option value="">{t("New input design")}</option>
        {catalog?.experiments.map(row => <option key={row.id} value={row.id}>
          {row.name} · {new Date(row.created_at).toLocaleString()}</option>)}
      </select></label>
      {record && <button className="ws-outlined" onClick={() => downloadFile(`input-design-${record.id}.json`, JSON.stringify(record, null, 2))}>
        {t("Download full experiment JSON")}
      </button>}
    </div>
    {error && <p className="ws-error" role="alert">{designError(error, catalog)}</p>}
    {!catalog && !error && <p role="status">{t("Opening input designs…")}</p>}
    {catalog && config && <>
      {record && <Results record={record} catalog={catalog} workspaceId={workspaceId} onPublished={onPublished} />}
      <details className="oed-editor" open={!record}>
        <summary>{record ? t("Edit settings and save a new experiment") : t("Configure input design")}</summary>
        <DesignForm catalog={catalog} config={config} setConfig={setConfig} name={name} setName={setName} saving={busy} generate={generate} />
      </details>
    </>}
  </>;
}
