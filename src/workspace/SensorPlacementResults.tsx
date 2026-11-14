import { useState, type ReactNode } from "react";
import { t as tr, useLocale } from "../i18n";
import { Plot } from "./Charts";
import { objectives, profiles, type Analysis, type Cancellation, type Evaluation, type Evidence, type Sensor, type Spectrum, type Subset, type TrajectoryRequest } from "./sensorPlacementTypes";

const palette = ["#9da8a2", "#a3e085", "#77c9ff", "#efb67a", "#d7a9ff", "#ff998b", "#6bdccc"];
const fault = (id: string) => tr("sensor-fault-" + id);
const conditionLabel = (id: string) => tr("sensor-condition-" + id);
const fmt = (value: number | null) => value == null ? "—" : value.toLocaleString(undefined, { maximumSignificantDigits: 4 });
const pct = (value: number) => value.toLocaleString(undefined, { style: "percent", maximumFractionDigits: 1 });

function Table({ headers, children }: { headers: string[]; children: ReactNode }) {
  return <div className="ws-table-scroll"><table><thead><tr>
    {headers.map((header, i) => <th scope="col" key={i}>{header}</th>)}
  </tr></thead><tbody>{children}</tbody></table></div>;
}

function Distance({ value, weak }: { value: number; weak: number }) {
  return <span className={value < weak ? "sensor-weak" : undefined}>
    {fmt(value)}{value < weak && <small> {tr(value <= 1e-10 ? "Indistinguishable" : "Weak")}</small>}
  </span>;
}

function Traces({ times, series, names, sensors, selected, onset }: {
  times: number[]; series: number[][][]; names: string[]; sensors: Sensor[]; selected: string[]; onset: number;
}) {
  const [cursor, setCursor] = useState<number>();
  const axis = { kind: "numeric" as const, column: null, origin: null, start: times[0], end: times.at(-1)! };
  return <>
    <div className="sensor-legend">{names.map((id, i) => <span key={id}><i style={{ backgroundColor: palette[i] }} />{fault(id)}</span>)}</div>
    {selected.map(key => {
      const i = sensors.findIndex(sensor => sensor.key === key);
      const sensor = sensors[i];
      return <Plot key={key} times={times} axis={axis} title={tr(sensor.label) + " · " + sensor.unit}
        values={series[0].map(row => row[i])} color={palette[0]} selectedTime={cursor}
        onHoverTime={setCursor} onSelectTime={setCursor} markers={[{ time: onset, label: tr("Fault onset") }]}
        overlays={series.slice(1).map((rows, j) => ({ times, values: rows.map(row => row[i]),
          title: fault(names[j+1]), color: palette[j+1] }))} />;
    })}
  </>;
}

function SubsetChart({ rows, selected, onSelect, label }: {
  rows: Subset[]; selected: Subset; onSelect: (row: Subset) => void; label: (keys: string[]) => string;
}) {
  const maxX = Math.max(1, ...rows.map(row => row.cost));
  const maxY = Math.max(.001, ...rows.map(row => row.worst.separation));
  const min = 52, right = 596, top = 26, bottom = 178;
  return <figure className="sensor-scatter">
    <figcaption>{tr("Minimum distance across conditions vs. installation cost")}</figcaption>
    <svg viewBox="0 0 628 221" role="group" aria-label={tr("Minimum distance across conditions vs. installation cost")}>
      {[0, .5, 1].map(f => <g key={f}>
        <line x1={min} x2={right} y1={bottom-(bottom-top)*f} y2={bottom-(bottom-top)*f} />
        <text x={min-7} y={bottom-(bottom-top)*f+4} textAnchor="end">{fmt(maxY*f)}</text>
        <text x={min+(right-min)*f} y={bottom+20} textAnchor="middle">{fmt(maxX*f)}</text>
      </g>)}
      {rows.map(row => <circle key={row.sensors.join()} role="button" tabIndex={0}
        aria-label={label(row.sensors)} aria-pressed={row === selected}
        className={row === selected ? "selected" : row.pareto ? "pareto" : "rejected"}
        cx={min+row.cost/maxX*(right-min)} cy={bottom-row.worst.separation/maxY*(bottom-top)}
        r={row === selected ? 8 : 5} onClick={() => onSelect(row)} onKeyDown={e => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(row); }
        }}><title>{label(row.sensors)} · {fmt(row.worst.separation)}</title></circle>)}
    </svg>
  </figure>;
}

function Matrix({ evidence, names, weak }: { evidence: Evidence; names: string[]; weak: number }) {
  const max = Math.max(1, ...evidence.distances.flat());
  return <Table headers={[tr("Hypothesis"), ...names.map(fault)]}>
    {evidence.distances.map((row, i) => <tr key={names[i]}>
      <th scope="row">{fault(names[i])}</th>
      {row.map((value, j) => <td key={names[j]} style={{ backgroundColor: i === j ? undefined : "rgba(136,198,118," + (.05 + .23*value/max) + ")" }}>
        {i === j ? "—" : <Distance value={value} weak={weak} />}
      </td>)}
    </tr>)}
  </Table>;
}

function Sensitivity({ evidence, parameters, sensors, subset, stability }: {
  evidence: Evidence; parameters: string[]; sensors: Sensor[]; subset: Subset;
  stability: Analysis["conditions"][number]["derivativeStability"];
}) {
  const max = Math.max(1, ...evidence.sensitivityNorms.flat());
  return <>
    <h3>{tr("Whitened sensitivity norms")}</h3>
    <p className="ws-muted">{tr("Norms span the sampled horizon. With correlated noise, Cholesky-whitened coordinates follow the listed sensor order.")}</p>
    <Table headers={[tr("Fault parameter"), ...subset.sensors.map(key => sensors.find(s => s.key === key)!.tag),
      tr("Maximum step-halving difference")]}>
      {parameters.map((key, i) => <tr key={key}><th scope="row">{fault(key)}</th>
        {evidence.sensitivityNorms[i].map((v, j) => <td key={subset.sensors[j]}
          style={{ backgroundColor: "rgba(136,198,118," + (.05 + .35*v/max) + ")" }}>{fmt(v)}</td>)}
        <td>{pct(Math.max(...subset.sensors.map(k => stability[i].relativeL2[sensors.findIndex(s => s.key === k)])))}</td>
      </tr>)}
    </Table>
  </>;
}

function SingularValues({ title, singular, columns }: { title: string; singular: Spectrum; columns: number }) {
  return <>
    <h3>{title}</h3>
    <p>{tr("Rank")} <b>{singular.rank}/{columns}</b> · {tr("Condition number")} <b>{singular.condition == null ? tr("Rank deficient") : fmt(singular.condition)}</b> · {tr("SVD rank tolerance")} {fmt(singular.tolerance)}</p>
    <ol className="sensor-spectrum">
      {singular.singularValues.map((value, i) => <li key={i}>
        <span>σ<sub>{i+1}</sub></span><meter min={0} max={singular.singularValues[0] || 1} value={value} aria-label={"σ" + (i+1)} /><b>{fmt(value)}</b>
      </li>)}
    </ol>
  </>;
}

function CancellationResults({ study, sensors, weak, label }: {
  study: Cancellation; sensors: Sensor[]; weak: number; label: (keys: string[]) => string;
}) {
  const [id, setId] = useState(study.cases[0].id);
  const scenario = study.cases.find(c => c.id === id)!;
  return <section className="ws-panel">
    <h2>{tr("Pump and valve cancellation experiment")}</h2>
    <p>{tr("A bounded search minimizes Tank 1 deviation over 12 seconds at equilibrium. The fitted intensity is frozen before applying the stress cases.")}</p>
    <p>{tr("Nominal Tank 1 RMS change (m)")} · {study.tank1Rms.map((rms, i) =>
      <span key={i}>{i > 0 ? " · " : ""}{fault(study.hypotheses[i+1])} <b>{fmt(rms)}</b></span>)}</p>
    <div className="sensor-fields"><label>{tr("Cancellation stress case")}<select value={id} onChange={e => setId(e.target.value)}>
      {study.cases.map(c => <option key={c.id} value={c.id}>{conditionLabel(c.id)}</option>)}
    </select></label></div>
    <p className="ws-muted">{fault("pump_degradation")} {pct(scenario.pumpIntensity)} · {fault("valve_restriction")} {pct(scenario.valveIntensity)} · {tr("Noise multiplier")} {fmt(scenario.noiseScale)}×</p>
    <p className="ws-muted">{tr("Gaussian reference power uses a 5% false alarm rate for the known combined template. Pair error assumes equal priors for the two stated faults.")}</p>
    <Table headers={[tr("Sensor layout"), tr("Detectability"), tr("Reference detection power"), tr("Isolability"), tr("Closest competing fault"), tr("Reference pair error")]}>
      {scenario.metrics.map(row => <tr key={row.sensors.join()}>
        <th scope="row">{label(row.sensors)}</th>
        <td><Distance value={row.detectability} weak={weak} /></td><td>{pct(row.detectionPower)}</td>
        <td><Distance value={row.isolability} weak={weak} /></td><td>{fault(row.competitor)}</td><td>{pct(row.nearestPairError)}</td>
      </tr>)}
    </Table>
    <h3>{tr("Cancellation trajectories")}</h3>
    <Traces key={id} times={study.times} series={scenario.templates} names={study.hypotheses} sensors={sensors} selected={["level1", "level2"]} onset={2} />
  </section>;
}

function EvaluationResults({ evaluation, names, label }: {
  evaluation: Evaluation; names: string[]; label: (keys: string[]) => string;
}) {
  const [cohort, setCohort] = useState(evaluation.cohorts[0].id);
  const [layoutId, setLayoutId] = useState(evaluation.chosenLayout);
  const layout = evaluation.layouts.find(row => row.id === layoutId)!;
  const metrics = layout.cohorts.find(row => row.id === cohort)!;
  return <section className="ws-panel">
    <h2>{tr("Held-out noisy observations")}</h2>
    <p>{tr("The detector uses frozen reference templates, the selected measurements, and a threshold calibrated on separate healthy noise. Timing and parameter mismatch are held out from sensor selection.")}</p>
    <p className="ws-muted">{tr("Calibration seed")} {evaluation.calibrationSeed} · {tr("Holdout seed")} {evaluation.holdoutSeed} · {tr("Trials per hypothesis")} {metrics.trialsPerHypothesis} · {tr("Target false alarm rate")} {pct(evaluation.targetFalseAlarm)}</p>
    <div className="sensor-fields"><label>{tr("Holdout cohort")}<select value={cohort} onChange={e => setCohort(e.target.value)}>
      {evaluation.cohorts.map(c => <option key={c.id} value={c.id}>{conditionLabel(c.id)}</option>)}
    </select></label></div>
    <Table headers={[tr("Comparison"), tr("Sensor layout"), tr("Installation cost"), tr("Detection rate"), tr("False alarm rate"),
      tr("Classification accuracy"), tr("Ambiguous rate"), tr("Unclassified rate"), tr("Minimum distance (design / holdout)"), tr("Runtime (ms)")]}>
      {evaluation.layouts.map(row => {
        const c = row.cohorts.find(item => item.id === cohort)!;
        return <tr key={row.id}><th scope="row">{tr("sensor-layout-" + row.id)}</th><td>{label(row.sensors)}</td>
          <td>{fmt(row.cost)}</td><td>{pct(c.detectionRate)}</td><td>{pct(c.falseAlarmRate)}</td>
          <td>{pct(c.classificationAccuracy)}</td><td>{pct(c.ambiguousRate)}</td><td>{pct(c.unclassifiedRate)}</td>
          <td>{fmt(row.minimumSeparation)} / {fmt(c.trueMinimumSeparation)}</td><td>{fmt(row.runtimeMs)}</td></tr>;
      })}
    </Table>
    <details><summary>{tr("Confusion counts and pairwise classification")}</summary>
      <div className="sensor-fields"><label>{tr("Comparison")}<select value={layoutId} onChange={e => setLayoutId(e.target.value)}>
        {evaluation.layouts.map(row => <option key={row.id} value={row.id}>{tr("sensor-layout-" + row.id)}</option>)}
      </select></label></div>
      <p className="ws-muted">{tr("Rows are simulated truth. Columns are detector decisions. Binary pairwise accuracy assumes two competing faults and counts abstentions in its denominator.")}</p>
      <Table headers={[tr("Hypothesis"), ...names.map(fault), tr("Ambiguous")]}>
        {metrics.counts.map((row, i) => <tr key={names[i]}><th scope="row">{fault(names[i])}</th>
          {row.map((count, j) => <td key={j}>{count}</td>)}</tr>)}
      </Table>
      <Table headers={[tr("Fault pair"), tr("Classification accuracy"), tr("Ambiguous rate")]}>
        {metrics.pairwise.map(row => <tr key={row.faults.join()}><th scope="row">{row.faults.map(fault).join(" / ")}</th>
          <td>{pct(row.accuracy)}</td><td>{pct(row.ambiguousRate)}</td></tr>)}
      </Table>
    </details>
  </section>;
}

export function SensorPlacementResults({ analysis, publish, busy }: {
  analysis: Analysis; publish: (request: TrajectoryRequest) => void; busy: boolean;
}) {
  useLocale();
  const { config, conditions, sensors, hypotheses, winners, weakDistance } = analysis;
  const objective = config.objective, profile = config.aggregation;
  const sorted = [...analysis.subsets].sort((a,b) => b[profile][objective]-a[profile][objective] || a.cost-b.cost);
  const [selection, setSelection] = useState(winners[profile].join());
  const [scope, setScope] = useState("all");
  const [condition, setCondition] = useState(conditions[0].id);
  const [hypothesis, setHypothesis] = useState(hypotheses[1]);
  const [mode, setMode] = useState("clean");
  const selected = sorted.find(row => row.sensors.join() === selection)!;
  const conditionIndex = conditions.findIndex(c => c.id === condition);
  const data = conditions[conditionIndex];
  const evidence = selected.conditions[conditionIndex];
  const label = (keys: string[]) => keys.map(key => sensors.find(s => s.key === key)!.tag).join(" + ");
  const cohort = analysis.evaluation.cohorts.find(c => c.id === mode);
  const times = cohort ? conditions[0].times : data.times;
  const series = cohort?.representative ?? (mode === "delta" ? data.signatures : data.templates);
  const rows = scope === "pareto" ? sorted.filter(row => row.pareto) : sorted;
  return <div className="sensor-results">
    <section className="ws-panel">
      <h2>{tr("Exact sensor subset comparison")}</h2>
      <p>{tr("Distances use independent Gaussian samples and the declared cross-sensor covariance. Weak separation is flagged below 2.")}</p>
      <div className="sensor-summary">{profiles.map(id => <button key={id} className="ws-outlined"
        onClick={() => setSelection(winners[id].join())}>
        <span>{tr("sensor-aggregation-" + id)}</span><strong>{label(winners[id])}</strong>
      </button>)}</div>
      <p className="ws-muted">{tr("Optimization objective")} · {tr("sensor-objective-" + objective)} · {sorted.length} {tr("Feasible subsets")} · {fmt(analysis.runtimeMs)} ms</p>
      <SubsetChart rows={sorted} label={label} selected={selected} onSelect={row => setSelection(row.sensors.join())} />
      <div className="sensor-legend">
        {([['#efb67a', 'Selected layout'], ['#a3e085', 'Pareto frontier'], ['#78877c', 'Other feasible layouts']] as const).map(([color, key]) =>
          <span key={key}><i style={{ backgroundColor: color }} />{tr(key)}</span>)}
      </div>
      <div className="sensor-fields"><label>{tr("Show configurations")}<select value={scope} onChange={e => setScope(e.target.value)}>
        <option value="all">{tr("All feasible configurations")}</option><option value="pareto">{tr("Pareto frontier")}</option>
      </select></label></div>
      <Table headers={[tr("Sensor layout"), tr("Installation cost"), ...profiles.map(id => tr("sensor-aggregation-" + id)), tr("Pareto frontier")]}>
        {rows.map(row => <tr key={row.sensors.join()} className={row === selected ? "sensor-selected-row" : ""}>
          <th scope="row"><button className="ws-outlined" aria-pressed={row === selected} onClick={() => setSelection(row.sensors.join())}>{label(row.sensors)}</button></th>
          <td>{fmt(row.cost)}</td>{profiles.map(id => <td key={id}>{fmt(row[id][objective])}</td>)}
          <td>{row.pareto ? tr("Yes") : "—"}</td>
        </tr>)}
      </Table>
    </section>
    <section className="ws-panel">
      <h2>{tr("Fault detectability and isolability")}</h2>
      <p>{tr("Detection compares against healthy operation. Isolation compares competing fault hypotheses. State observability concerns reconstruction of internal states and is outside this analysis.")}</p>
      <div className="sensor-fields"><label>{tr("Inspect operating condition")}<select value={condition} onChange={e => {
        setCondition(e.target.value); setMode("clean");
      }}>{conditions.map(c => <option key={c.id} value={c.id}>{conditionLabel(c.id)}</option>)}</select></label></div>
      <p>{label(selected.sensors)} · {tr("Minimum detectability")} <b><Distance value={evidence.detectability} weak={weakDistance} /></b> · {tr("Minimum isolability")} <b><Distance value={evidence.isolability} weak={weakDistance} /></b></p>
      <details><summary>{tr("Scores by operating condition")}</summary>
        <Table headers={[tr("Operating condition"), ...objectives.map(id => tr("sensor-score-" + id))]}>
          {conditions.map((item, i) => <tr key={item.id} className={i === conditionIndex ? "sensor-selected-row" : ""}>
            <th scope="row">{conditionLabel(item.id)}</th>
            {objectives.map(key => <td key={key}>{fmt(selected.conditions[i][key])}</td>)}
          </tr>)}
        </Table>
      </details>
      <Matrix evidence={evidence} names={hypotheses} weak={weakDistance} />
      <Sensitivity evidence={evidence} parameters={analysis.parameters} sensors={sensors} subset={selected} stability={data.derivativeStability} />
      <SingularValues title={tr("Sensitivity singular values")} singular={evidence.spectrum} columns={analysis.parameters.length} />
      <SingularValues title={tr("Nonlinear signature singular values")} singular={evidence.signatureSpectrum} columns={hypotheses.length-1} />
    </section>
    <section className="ws-panel">
      <h2>{tr("Fault trajectories")}</h2>
      <div className="sensor-fields"><label>{tr("Trajectory view")}<select value={mode} onChange={e => setMode(e.target.value)}>
        <option value="clean">{tr("Simulated measurement")}</option><option value="delta">{tr("Change from healthy")}</option>
        {conditionIndex === 0 && analysis.evaluation.cohorts.map(c => <option key={c.id} value={c.id}>{conditionLabel(c.id)}</option>)}
      </select></label></div>
      <Traces key={condition + mode} times={times} series={series} names={hypotheses} sensors={sensors}
        selected={selected.sensors} onset={Number(cohort?.model.start ?? config.onset)} />
      <div className="sensor-fields">
        <label>{tr("Trajectory to publish")}<select value={hypothesis} onChange={e => setHypothesis(e.target.value)}>
          {hypotheses.map(id => <option key={id} value={id}>{fault(id)}</option>)}
        </select></label>
        <button className="ws-outlined" disabled={busy || mode === "delta"} onClick={() =>
          publish({ condition, hypothesis, sensors: selected.sensors, cohort: cohort?.id })}>{tr("Publish trajectory to Signal Explorer")}</button>
      </div>
    </section>
    <CancellationResults study={analysis.cancellation} sensors={sensors} weak={weakDistance} label={label} />
    <EvaluationResults evaluation={analysis.evaluation} names={hypotheses} label={label} />
  </div>;
}
