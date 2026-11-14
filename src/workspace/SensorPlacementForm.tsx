import { useState, type FormEvent } from "react";
import { t as tr } from "../i18n";
import { objectives, profiles, type Options, type SensorMode, type Setup } from "./sensorPlacementTypes";

export function Numeric({ label, value, onChange, min, max, step = "any", optional = false }: {
  label: string; value: number | null; onChange: (n: number | null) => void; min?: number;
  max?: number; step?: number | "any"; optional?: boolean;
}) {
  return <label>{label}<input type="number" value={value ?? ""} onChange={event => onChange(
    Number.isFinite(event.target.valueAsNumber) ? event.target.valueAsNumber : null
  )} min={min} max={max} step={step} required={!optional} /></label>;
}

export function SensorPlacementForm({ options, config, setConfig, name, setName, onRun, busy }: {
  options: Options; config: Setup; setConfig: (config: Setup) => void; name: string;
  setName: (name: string) => void; onRun: (event: FormEvent) => void; busy: boolean;
}) {
  const [conditionId, setConditionId] = useState<string | null>(null);
  const inspected = config.conditions.find(c => c.id === conditionId) ?? config.conditions[0];
  const set = <K extends keyof Setup>(key: K, value: Setup[K]) => setConfig({ ...config, [key]: value });
  const changeSensor = (index: number, update: Partial<Setup["sensors"][number]>) =>
    set("sensors", config.sensors.map((sensor, i) => i === index ? { ...sensor, ...update } : sensor));
  const conditionName = (id: string) => tr("sensor-condition-" + id);
  return <form className="ws-panel sensor-form" onSubmit={onRun}>
    <fieldset disabled={busy}>
      <legend>{tr("Study settings")}</legend>
      <div className="sensor-fields">
        <label>{tr("Analysis name")}<input required maxLength={160} value={name} onChange={e => setName(e.target.value)} /></label>
        <label>{tr("Process model")}<select value={config.modelId} onChange={e => set("modelId", e.target.value)}>
          {options.models.map(model => <option key={model.id} value={model.id}>{tr(model.name)} · {model.version}</option>)}
        </select></label>
        <Numeric label={tr("Prediction horizon (s)")} value={config.horizon} onChange={v => set("horizon", v!)} min={4} max={120} />
        <Numeric label={tr("Sample interval (s)")} value={config.step} onChange={v => set("step", v!)} min={.1} max={5} />
        <Numeric label={tr("Fault onset (s)")} value={config.onset} onChange={v => set("onset", v!)} min={0} max={119} />
        <Numeric label={tr("Fault duration (s), blank for persistent")} value={config.duration} onChange={v => set("duration", v)} min={.01} max={120} optional />
      </div>
      <h3>{tr("Operating conditions")}</h3>
      <p className="ws-muted">{tr("The reference condition anchors the nominal optimization and held-out detector.")}</p>
      <div className="sensor-checks">{options.conditions.map(id => {
        const selected = config.conditions.some(c => c.id === id);
        return <label key={id}><input type="checkbox" checked={selected} disabled={selected && config.conditions.length === 1}
          onChange={e => set("conditions", e.target.checked ? [...config.conditions, { id, parameters: {} }] :
            config.conditions.filter(c => c.id !== id))} />{conditionName(id)}</label>;
      })}</div>
      <div className="sensor-fields">
        <label>{tr("Reference condition")}<select value={config.conditions[0].id} onChange={e => {
          const reference = config.conditions.find(c => c.id === e.target.value)!;
          set("conditions", [reference, ...config.conditions.filter(c => c !== reference)]);
        }}>{config.conditions.map(c => <option key={c.id} value={c.id}>{conditionName(c.id)}</option>)}</select></label>
      </div>
      <details><summary>{tr("Override operating parameters")}</summary>
        <div className="sensor-fields">
          <label>{tr("Operating condition")}<select value={inspected.id} onChange={e => setConditionId(e.target.value)}>
            {config.conditions.map(c => <option key={c.id} value={c.id}>{conditionName(c.id)}</option>)}
          </select></label>
          {options.modelFields.map(field => <Numeric key={field.key} label={tr(field.label) + (field.unit ? " (" + field.unit + ")" : "")}
            min={field.min} max={field.max} value={inspected.parameters[field.key] ?? null} optional onChange={value => {
              const parameters = { ...inspected.parameters };
              if (value == null) delete parameters[field.key]; else parameters[field.key] = value;
              set("conditions", config.conditions.map(c => c.id === inspected.id ? { ...c, parameters } : c));
            }} />)}
        </div>
      </details>
      <h3>{tr("Candidate measurements")}</h3>
      <p className="ws-muted">{tr("Pump command and valve command are known inputs. Flow sensors require positive measurement noise.")}</p>
      <div className="ws-table-scroll"><table><thead><tr>
        {[tr("Signal"), tr("Sensor status"), tr("Noise standard deviation"), tr("Installation cost")].map(label => <th key={label}>{label}</th>)}
      </tr></thead><tbody>{options.sensors.map((sensor, i) => {
        const label = tr(sensor.label);
        const row = config.sensors[i];
        return <tr key={sensor.key}>
          <th scope="row">{label} <span className="ws-muted">{sensor.tag}</span></th>
          <td><select aria-label={label + " · " + tr("Sensor status")} value={row.mode}
            onChange={e => changeSensor(i, { mode: e.target.value as SensorMode })}>
            {(["available", "required", "excluded"] as const).map(mode => <option key={mode} value={mode}>{tr("sensor-mode-" + mode)}</option>)}
          </select></td>
          <td><input type="number" aria-label={label + " · " + tr("Noise standard deviation")} min={1e-7} max={10}
            value={row.noise ?? ""} step="any" required onChange={e => changeSensor(i, { noise: e.target.valueAsNumber })} /> {sensor.unit}</td>
          <td><input type="number" aria-label={label + " · " + tr("Installation cost")} min={0} max={100000}
            value={row.cost ?? ""} step="any" required onChange={e => changeSensor(i, { cost: e.target.valueAsNumber })} /></td>
        </tr>;
      })}</tbody></table></div>
      <details><summary>{tr("Cross-sensor correlations")}</summary>
        <div className="sensor-fields">
          {options.sensors.flatMap((a, i) => options.sensors.slice(i+1).map((b, offset) => {
            const j = i+1+offset;
            return <Numeric key={a.key + b.key} label={a.tag + " / " + b.tag} value={config.correlations[i][j]} min={-1} max={1}
              onChange={value => set("correlations", config.correlations.map((row, r) => row.map((v, c) =>
                (r === i && c === j) || (r === j && c === i) ? value! : v)))} />;
          }))}
        </div>
      </details>
      <h3>{tr("Fault hypotheses")}</h3>
      <div className="sensor-checks">{[...Object.keys(options.defaults.intensities), "pump_and_valve", "pump_and_leak"].map(id =>
        <label key={id}><input type="checkbox" checked={config.hypotheses.includes(id)} onChange={e => set("hypotheses",
          e.target.checked ? [...config.hypotheses, id] : config.hypotheses.filter(k => k !== id))} />{tr("sensor-fault-" + id)}</label>
      )}</div>
      <div className="sensor-fields">{Object.entries(config.intensities).map(([id, value]) =>
        <Numeric key={id} label={tr("sensor-fault-" + id) + " · " + tr("Intensity")} min={0} max={1} value={value}
          onChange={v => set("intensities", { ...config.intensities, [id]: v! })} />)}</div>
      <h3>{tr("Sensor design constraints")}</h3>
      <div className="sensor-fields">
        <Numeric label={tr("Installation budget")} value={config.budget} onChange={v => set("budget", v!)} min={0} max={100000} />
        <Numeric label={tr("Maximum sensor count")} value={config.maxSensors} onChange={v => set("maxSensors", v!)} min={1} max={5} step={1} />
        <label>{tr("Optimization objective")}<select value={config.objective} onChange={e => set("objective", e.target.value as Setup["objective"])}>
          {objectives.map(id => <option key={id} value={id}>{tr("sensor-objective-" + id)}</option>)}
        </select></label>
        <label>{tr("Condition aggregation")}<select value={config.aggregation} onChange={e => set("aggregation", e.target.value as Setup["aggregation"])}>
          {profiles.map(id => <option key={id} value={id}>{tr("sensor-aggregation-" + id)}</option>)}
        </select></label>
      </div>
      <button className="ws-primary" disabled={config.hypotheses.length < 2}>{tr("Run, optimize and save")}</button>
      {config.hypotheses.length < 2 && <p className="ws-muted">{tr("Select at least two distinct fault hypotheses.")}</p>}
    </fieldset>
  </form>;
}
