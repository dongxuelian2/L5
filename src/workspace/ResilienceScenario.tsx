import { t as tr } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { useEffect, useId, useState, type FormEvent } from "react";
import { api, message } from "./api";
import { number } from "./types";
import type { Catalog, FaultEvent, FaultSchedule, Model, NumberField, Scenario, Signal } from "./resilienceTypes";

export function signalName(signal: Signal) {
  return `${signal.tag} · ${tr(signal.label)}`;
}

export function faultName(type: string) { return tr(`resilience fault ${type}`); }
export function targetName(target: string) { return tr(`resilience target ${target}`); }

export function NumericInput({ label, value, onChange, min, max, integer, optional = false }: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  integer?: boolean;
  optional?: boolean;
}) {
  return <label>{label}<input type="number" value={value ?? ""} step={integer ? 1 : "any"} min={min} max={max} required={!optional}
    onChange={event => onChange(event.target.value === "" ? null : Number(event.target.value))} /></label>;
}

export function NumericFields<T extends number | null>({ fields, values, onChange }: {
  fields: NumberField[];
  values: Record<string, T>;
  onChange: (key: string, value: number | null) => void;
}) {
  return <div className="ws-form-grid ws-three">
    {fields.map(field => <NumericInput key={field.key} label={tr(field.label) + (field.unit ? ` (${tr(field.unit)})` : "")}
      value={values[field.key] === undefined ? field.default : values[field.key]} min={field.min} max={field.max}
      integer={field.type === "integer"} optional={field.nullable} onChange={value => onChange(field.key, value ?? field.default)} />)}
  </div>;
}

export function FaultTimeline({ faults, duration, selectedId, onSelect, detections }: {
  faults: FaultSchedule[];
  duration: number;
  selectedId?: string;
  onSelect?: (id: string) => void;
  detections?: ReadonlyMap<string, number>;
}) {
  const pct = (seconds: number) => `${Math.max(0, Math.min(100, seconds / Math.max(duration, .0001) * 100))}%`;
  return <div className="resilience-timeline">
    <div className="resilience-timeline-row" aria-hidden="true">
      <span>{tr("Simulation clock")}</span>
      <div className="resilience-ticks">{[0, .25, .5, .75, 1].map(tick => <span key={tick}>{number(tick * duration)} s</span>)}</div>
    </div>
    {faults.map(fault => {
      const label = `${faultName(fault.type)} · ${targetName(fault.target)}`;
      const time = detections?.get(fault.id);
      return <div className="resilience-timeline-row" key={fault.id}>
        {onSelect ? <button className="resilience-track-label" type="button" aria-pressed={selectedId === fault.id} onClick={() => onSelect(fault.id)}>{label}</button> : <span>{label}</span>}
        <div className="resilience-track" aria-label={`${label} · ${number(fault.onset)} s`}>
          {fault.intervals.map(({ start, end }) => <span key={start} className="resilience-active-span" style={{ left: pct(start), width: pct(end - start) }} title={`${number(start)}–${number(end)} s`} />)}
          {time !== undefined && <span className="resilience-alarm-mark" style={{ left: pct(time) }} title={`${tr("Matched alarm")} · ${number(time)} s`} />}
        </div>
      </div>;
    })}
    {!faults.length && <p className="ws-muted">{tr("Healthy schedule. No faults configured.")}</p>}
  </div>;
}

function FaultEditor({ event, catalog, model, duration, update, remove }: {
  event: FaultEvent;
  catalog: Catalog;
  model: Model;
  duration: number;
  update: (event: FaultEvent) => void;
  remove: () => void;
}) {
  const fault = catalog.fault_types.find(item => item.id === event.type);
  const profile = catalog.profiles.find(item => item.id === event.profile);
  const fields = [...(fault?.parameters ?? []), ...(profile?.parameters ?? [])];
  const signalByKey = new Map(model.signals.map(signal => [signal.key, signal]));
  function selectProfile(id: string) {
    const parameters = Object.fromEntries((fault?.parameters ?? [])
      .filter(field => event.parameters[field.key] !== undefined).map(field => [field.key, event.parameters[field.key]]));
    const recovery = id === "temporary" && event.recovery === null ? (event.onset + duration) / 2 : event.recovery;
    update({ ...event, profile: id, recovery, parameters });
  }
  return <fieldset className="resilience-event-fields">
    <legend>{tr("Edit fault event")} · {event.id}</legend>
    <div className="ws-form-grid ws-three">
      <label>{tr("Fault type")}<select value={event.type} onChange={change => {
        const next = catalog.fault_types.find(item => item.id === change.target.value);
        if (!next) return;
        const parameters = Object.fromEntries((profile?.parameters ?? [])
          .filter(field => !next.parameters.some(other => other.key === field.key))
          .filter(field => event.parameters[field.key] !== undefined).map(field => [field.key, event.parameters[field.key]]));
        update({ ...event, type: next.id, target: next.targets.includes(event.target) ? event.target : next.targets[0], parameters });
      }}>{catalog.fault_types.map(item => <option key={item.id} value={item.id}>{faultName(item.id)}</option>)}</select></label>
      <label>{tr("Target")}<select value={event.target} onChange={change => update({ ...event, target: change.target.value })}>
        {fault?.targets.map(target => {
          const signal = signalByKey.get(target);
          return <option value={target} key={target}>{signal && fault?.id !== "pump_degradation" && fault?.id !== "valve_restriction" ? signalName(signal) : targetName(target)}</option>;
        })}
      </select></label>
      <label>{tr("Evolution profile")}<select value={event.profile} onChange={change => selectProfile(change.target.value)}>
        {catalog.profiles.map(item => <option key={item.id} value={item.id}>{tr(`resilience profile ${item.id}`)}</option>)}
      </select></label>
      <NumericInput label={tr("Fault onset (s)")} min={0} max={duration} value={event.onset} onChange={onset => update({ ...event, onset: onset ?? 0 })} />
      <NumericInput label={tr("Recovery time (s)")} min={event.onset} max={duration} value={event.recovery} optional={event.profile !== "temporary"} onChange={recovery => update({ ...event, recovery })} />
      <NumericInput label={tr("Severity (0–1)")} min={0} max={1} value={event.severity} onChange={severity => update({ ...event, severity: severity ?? 0 })} />
    </div>
    <p className="ws-muted">{tr(event.profile + " profile description")}</p>
    {!!fields.length && <NumericFields fields={fields} values={event.parameters} onChange={(key, value) => update({ ...event, parameters: { ...event.parameters, [key]: value } })} />}
    <button type="button" className="ws-outlined ws-danger" onClick={remove}>{tr("Remove fault")}</button>
  </fieldset>;
}

export function ResilienceScenario({ catalog, scenario, onChange, base, busy, onSave, onRun, saved }: {
  catalog: Catalog;
  scenario: Scenario;
  onChange: (value: Scenario) => void;
  base: string;
  busy: boolean;
  onSave: () => void;
  onRun: () => void;
  saved: boolean;
}) {
  const [schedule, setSchedule] = useState<FaultSchedule[] | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [selection, setSelection] = useState("");
  const id = useId();
  const model = catalog.models.find(item => item.id === scenario.model_id) ?? catalog.models[0];
  const event = scenario.faults.find(item => item.id === selection) ?? scenario.faults[0];
  const measurement = scenario.measurement;
  useEffect(() => {
    const controller = new AbortController();
    setSchedule(null);
    setPreviewError("");
    if (!scenario.faults.length) return;
    const timeout = window.setTimeout(() => {
      api<{ schedule: FaultSchedule[] }>(`${base}/preview`, { scenario }, "POST", controller.signal)
        .then(data => { if (!controller.signal.aborted) setSchedule(data.schedule); })
        .catch(error => { if (!controller.signal.aborted) setPreviewError(message(error)); });
    }, 220);
    return () => { controller.abort(); window.clearTimeout(timeout); };
  }, [base, scenario]);
  const pendingSchedule = scenario.faults.map(fault => ({
    ...fault,
    intervals: fault.severity > 0 ? [{ start: fault.onset, end: fault.recovery ?? scenario.duration }] : [],
  }));
  function addFault() {
    const first = catalog.fault_types[0];
    if (!first) return;
    const used = new Set(scenario.faults.map(fault => fault.id));
    let sequence = 1;
    while (used.has(`fault-${sequence}`)) sequence++;
    const fault: FaultEvent = {
      id: `fault-${sequence}`, type: first.id, target: first.targets[0], onset: Math.round(scenario.duration * .25 * 100) / 100,
      recovery: null, severity: .6, profile: "step", parameters: {},
    };
    onChange({ ...scenario, faults: [...scenario.faults, fault] });
    setSelection(fault.id);
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const button = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    if (button?.value === "save") onSave();
    else onRun();
  }
  return <form className="resilience-editor" onSubmit={submit}>
    <section className="ws-panel">
      <div className="ws-section-heading"><h2>{tr("Scenario composer")}</h2></div>
      <div className="ws-form-grid">
        <label>{tr("Scenario name")}<input required maxLength={160} value={scenario.name ?? ""} onChange={e => onChange({ ...scenario, name: e.target.value })} /></label>
        <label>{tr("Physical process model")}<select value={scenario.model_id} onChange={e => {
          const next = catalog.models.find(item => item.id === e.target.value);
          if (next) onChange({ ...catalog.defaults, name: scenario.name, model_id: next.id });
        }}>{catalog.models.map(item => <option value={item.id} key={item.id}>{tr(item.name)} · v{item.version}</option>)}</select></label>
      </div>
      <div className="ws-form-grid ws-three">
        <NumericInput label={tr("Simulation duration (s)")} min={.1} value={scenario.duration} onChange={duration => onChange({ ...scenario, duration: duration ?? .1 })} />
        <NumericInput label={tr("Sampling interval (s)")} min={.02} max={10} value={scenario.sample_interval} onChange={sample_interval => onChange({ ...scenario, sample_interval: sample_interval ?? .2 })} />
        <NumericInput label={tr("Random seed")} min={0} max={2147483647} integer value={scenario.seed} onChange={seed => onChange({ ...scenario, seed: seed ?? 1 })} />
      </div>
      <details><summary>{tr("Initial conditions and model parameters")}</summary>
        <NumericFields fields={[...model.initial, ...model.parameters]} values={{ ...scenario.initial, ...scenario.parameters }} onChange={(key, value) => {
          const group = model.initial.some(field => field.key === key) ? "initial" : "parameters";
          if (value !== null) onChange({ ...scenario, [group]: { ...scenario[group], [key]: value } });
        }} />
        <NumericInput label={tr("Maximum integration step (s)")} min={.005} max={.25} value={scenario.integration_step} onChange={integration_step => onChange({ ...scenario, integration_step: integration_step ?? .05 })} />
      </details>
      <details><summary>{tr("Noise, missing data and visible signals")}</summary>
        <div className="ws-form-grid ws-three">
          <NumericInput label={tr("Level sensor noise (m)")} min={0} max={.1} value={measurement.noise} onChange={noise => onChange({ ...scenario, measurement: { ...measurement, noise: noise ?? 0 } })} />
          <NumericInput label={tr("Random missing fraction")} min={0} max={1} value={measurement.missing_fraction} onChange={missing_fraction => onChange({ ...scenario, measurement: { ...measurement, missing_fraction: missing_fraction ?? 0 } })} />
          <NumericInput label={tr("Relative inlet disturbance")} min={0} max={1} value={measurement.physical_noise} onChange={physical_noise => onChange({ ...scenario, measurement: { ...measurement, physical_noise: physical_noise ?? 0 } })} />
        </div>
        <fieldset><legend>{tr("Visible signals")}</legend><div className="resilience-options">
          {model.signals.map(signal => <label key={signal.key}><input type="checkbox" checked={measurement.signals.includes(signal.key)}
            disabled={measurement.signals.length === 1 && measurement.signals[0] === signal.key}
            onChange={e => onChange({ ...scenario, measurement: { ...measurement, signals: e.target.checked
              ? [...measurement.signals, signal.key] : measurement.signals.filter(key => key !== signal.key) } })} />{signalName(signal)}</label>)}
        </div></fieldset>
      </details>
    </section>
    <section className="ws-panel" aria-labelledby={id}>
      <div className="ws-section-heading"><h2 id={id}>{tr("Fault schedule")}</h2>
        <button type="button" className="ws-outlined" onClick={addFault} disabled={scenario.faults.length >= catalog.limits.max_faults}>{tr("Add fault")}</button>
      </div>
      <FaultTimeline duration={scenario.duration} faults={schedule ?? pendingSchedule} selectedId={event?.id} onSelect={setSelection} />
      {previewError && <p role="alert" className="ws-error">{errorMessage(previewError)}</p>}
      {!!scenario.faults.length && !schedule && !previewError && <p role="status" className="ws-muted">{tr("Validating fault schedule…")}</p>}
      {event && <FaultEditor event={event} model={model} catalog={catalog} duration={scenario.duration}
        update={next => onChange({ ...scenario, faults: scenario.faults.map(fault => fault.id === next.id ? next : fault) })}
        remove={() => onChange({ ...scenario, faults: scenario.faults.filter(fault => fault.id !== event.id) })} />}
      <div className="resilience-actions">
        <button type="submit" className="ws-outlined" value="save" disabled={busy}>{tr(saved ? "Update saved scenario" : "Save scenario")}</button>
        <button type="submit" className="ws-primary" value="run" disabled={busy}>{tr("Run simulation")}</button>
      </div>
    </section>
  </form>;
}
