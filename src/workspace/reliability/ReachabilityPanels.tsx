import { Plot } from "../Charts";
import { fmt, label, pair } from "./ReachabilityMap";
import type { Analysis, Box, Config, Evaluation, Index, Pair, PlantKey, Scenario, Strategy } from "./reachabilityTypes";
import type { TimeAxis } from "../types";

export const strategies: Strategy[] = ["policy", "hold", "drain", "fill"];
export const plantKeys: PlantKey[] = ["area1", "area2", "connection", "outlet", "pumpRate", "outletValve", "tankHeight"];
export const changedPair = (current: Pair, i: number, value: number): Pair => i === 0 ? [value, current[1]] : [current[0], value];

export function Numeric({ name, value, set }: { name: string; value: number; set: (v: number) => void }) {
  return <label>{label(name)}<input type="number" step="any" value={Number.isFinite(value) ? value : ""}
    onChange={e => set(e.currentTarget.valueAsNumber)} /></label>;
}

export function Settings({ config, update, index, scenario, chooseScenario, incidentId, setIncidentId }: {
  config: Config; update: (c: Config) => void; index: Index; scenario: Scenario | null; chooseScenario: (id: string) => void;
  incidentId: string; setIncidentId: (id: string) => void;
}) {
  return <>
    <div className="ws-form-grid">
      <label>{label("model")}<select value={config.modelId} onChange={e => update({ ...config, modelId: e.target.value })}>
        <option value="coupled-tanks">{label("coupled")}</option>
      </select></label>
      <label>{label("scenario")}<select value={scenario?.id ?? ""} onChange={e => chooseScenario(e.target.value)}>
        <option value="">{label("defaultPlant")}</option>
        {scenario && !index.scenarios.some(s => s.id === scenario.id) && <option value={scenario.id}>{scenario.name} · v{scenario.version}</option>}
        {index.scenarios.map(s => <option value={s.id} key={s.id}>{s.name} · v{s.id === scenario?.id ? scenario.version : s.version}</option>)}
      </select></label>
    </div>
    <details open><summary>{label("regions")}</summary>
      <div className="reach-regions">{(["safe", "target"] as const).map(region => <fieldset key={region}><legend>{label(region)}</legend>
        <div className="ws-form-grid">{config[region].flatMap((bounds, tank) => bounds.map((v, bound) => <Numeric
          key={tank + "-" + bound} name={"limit" + tank + bound} value={v} set={value => {
            const box: Box = [...config[region]];
            box[tank] = changedPair(bounds, bound, value);
            update({ ...config, [region]: box });
          }} />))}</div>
      </fieldset>)}</div>
    </details>
    <details><summary>{label("actuators")}</summary><div className="ws-form-grid">
      {(["pump", "valve", "slew", "actionCounts"] as const).flatMap(key => config[key].map((v, i) =>
        <Numeric key={key + i} name={key + i} value={v} set={value => update({ ...config, [key]: changedPair(config[key], i, value) })} />))}
    </div><p className="ws-muted">{label("slewHint")}</p></details>
    <details><summary>{label("plant")}</summary><div className="ws-form-grid">
      {plantKeys.map(key => <Numeric key={key} name={key} value={config.plant[key]} set={value => update({ ...config, plant: { ...config.plant, [key]: value } })} />)}
    </div><p className="ws-muted">{label("scenarioHint")}</p></details>
    <details open><summary>{label("planning")}</summary><div className="ws-form-grid">
      {config.grid.map((v, i) => <Numeric key={i} name={"grid" + i} value={v} set={value => update({ ...config, grid: changedPair(config.grid, i, value) })} />)}
      {(["horizon", "controlSeconds", "integrationStep"] as const).map(key =>
        <Numeric key={key} name={key} value={config[key]} set={value => update({ ...config, [key]: value })} />)}
      <label>{label("mode")}<select value={config.mode} onChange={e => update({ ...config, mode: e.target.value as Config["mode"] })}>
        <option value="nominal">{label("nominal")}</option><option value="robust">{label("robust")}</option>
      </select></label>
    </div>
    {config.mode === "robust" && <fieldset><legend>{label("modeledDisturbances")}</legend>
      <div className="reach-checks">{Object.entries(index.disturbances).filter(([key]) => key !== "nominal").map(([key, parameters]) =>
        <label key={key}><input type="checkbox" checked={config.disturbances.includes(key)} onChange={e => update({
          ...config, disturbances: e.target.checked ? [...config.disturbances, key] : config.disturbances.filter(v => v !== key),
        })} />{label(key)} <small>{Object.entries(parameters).map(([k, v]) => label("effect-" + k) + " " + fmt(v)).join(", ")}</small></label>)}</div>
      <p className="ws-muted">{label("robustHint")}</p>
    </fieldset>}</details>
    {index.incidents.length > 0 && <label>{label("incident")}<select value={incidentId} onChange={e => setIncidentId(e.target.value)}>
      <option value="">{label("noIncident")}</option>{index.incidents.map(i => <option key={i.id} value={i.id}>{i.title}</option>)}
    </select></label>}
  </>;
}

export function ResultMetrics({ data, previous }: { data: Analysis; previous: number }) {
  const n = data.numerical;
  const count = (ranks: number[][]) => ranks.filter(row => row[previous] >= 0).length;
  return <dl className="reach-metrics">
    <div><dt>{label("reachedCells")}</dt><dd>{count(data.ranks)} / {data.safe.filter(Boolean).length}</dd></div>
    <div><dt>{label("viableCells")}</dt><dd>{data.viable.filter(row => row[previous]).length}</dd></div>
    <div><dt>{label("viableTarget")}</dt><dd>{count(data.viableTargetRanks)}</dd></div>
    <div><dt>{label("fixedPoint")}</dt><dd>{n.viabilityIterations} · {label(n.convergence ? "converged" : "incomplete")}</dd></div>
    {data.config.mode === "robust" && <>
      <div><dt>{label("nominalCells")}</dt><dd>{count(data.nominalRanks)} / {data.nominalViable.filter(row => row[previous]).length}</dd></div>
      <div><dt>{label("nominalIterations")}</dt><dd>{n.nominalViabilityIterations}</dd></div>
    </>}
  </dl>;
}

export function Comparison({ evaluation, strategy, setStrategy }: {
  evaluation: Evaluation; strategy: Strategy; setStrategy: (s: Strategy) => void;
}) {
  const replay = evaluation.replays[strategy], times = replay.trajectory.map(p => p.t);
  const axis: TimeAxis = { kind: "numeric", origin: null, column: "t", start: times[0], end: times[times.length - 1] };
  return <section className="reach-panel">
    <h2>{label("comparison")}</h2>
    <p className="ws-muted">{label(evaluation.initial.disturbance)} · {label("replayStep")} ≤ {fmt(evaluation.integrationStep)} s</p>
    <div className="reach-table"><table><thead><tr>
      {["strategy", "status", "recoveryTime", "margin", "movement", "effort", "violations"].map(key => <th key={key}>{label(key)}</th>)}
    </tr></thead><tbody>{strategies.map(key => {
      const run = evaluation.replays[key];
      return <tr key={key} data-active={key === strategy}>
        <th scope="row"><button className="ws-outlined" type="button" aria-pressed={key === strategy} onClick={() => setStrategy(key)}>{label(key)}</button></th>
        <td>{label(run.status)}</td><td>{fmt(run.recoverySeconds)}</td><td>{fmt(run.minimumMargin)}</td>
        <td>{pair(run.movement)}</td><td>{pair(run.effort)}</td><td>{run.violations.length}</td>
      </tr>;
    })}</tbody></table></div>
    <Plot title={label("margin")} times={times} values={replay.trajectory.map(p => p.safetyMargin)} threshold={0} thresholdLabel={label("safetyLimit")} axis={axis} />
    <details open><summary>{label("commands")} · {label(strategy)}</summary>
      {replay.actions.length ? <div className="reach-table reach-commands"><table><thead><tr>
        {["time", "pumpCommand", "valveCommand", "disturbance"].map(v => <th key={v}>{label(v)}</th>)}
      </tr></thead><tbody>{replay.actions.map(c => <tr key={c.t}><td>{fmt(c.t)}</td><td>{fmt(c.pump)}</td><td>{fmt(c.valve)}</td><td>{label(c.disturbance)}</td></tr>)}</tbody></table></div>
        : <p className="ws-muted">{label("noCommands")}</p>}
    </details>
  </section>;
}
