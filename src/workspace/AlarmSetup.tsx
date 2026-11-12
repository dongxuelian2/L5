import { useMemo, useState, type FormEvent } from "react";
import { t as tr } from "../i18n";
import { algorithms } from "./AlgorithmControls";
import { dateLabel, type Dataset, type Job } from "./types";
import { defaultAlarmPolicy, type AlarmPolicy, type AlarmSession, type AlarmSignal } from "./alarmTypes";

export function priorityLabel(policy: AlarmPolicy, id: string) {
  const priority = policy.priorities.find(item => item.id === id);
  if (!priority) return id;
  return defaultAlarmPolicy.priorities.some(item => item.id === id && item.label === priority.label)
    ? tr(priority.label) : priority.label;
}

type NumberKey = "proximitySeconds" | "repeatWindowSeconds" | "minSamples" | "minDurationSeconds"
  | "floodWindowSeconds" | "maxShelveSeconds" | "escalationSeconds";
const policyFields: { key: NumberKey; label: string; min: number; step: string }[] = [
  { key: "proximitySeconds", label: "Correlation window (s)", min: 0, step: "any" },
  { key: "repeatWindowSeconds", label: "Repeat window (s, 0 disables)", min: 0, step: "any" },
  { key: "minSamples", label: "Minimum alarm samples", min: 1, step: "1" },
  { key: "minDurationSeconds", label: "Minimum alarm duration (s)", min: 0, step: "any" },
  { key: "floodWindowSeconds", label: "Arrival window (s)", min: 1, step: "any" },
  { key: "maxShelveSeconds", label: "Maximum shelving time (s)", min: 1, step: "any" },
  { key: "escalationSeconds", label: "Escalate after (s, optional)", min: 1, step: "any" },
];

const emptySignal: AlarmSignal = { datasetId: "", signal: "" };
const signalKey = (value: AlarmSignal) => JSON.stringify([value.datasetId, value.signal]);

export function AlarmSetup({ datasets, jobs, basedOn, busy, onCreate, onCancel }: {
  datasets: Dataset[]; jobs: Job[]; basedOn: AlarmSession | null; busy: boolean;
  onCreate: (name: string, analysisIds: string[], policy: AlarmPolicy) => void; onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [selected, setSelected] = useState(basedOn?.analysisIds.filter(id => jobs.some(job => job.id === id)) || []);
  const [policy, setPolicy] = useState(basedOn?.policy || defaultAlarmPolicy);
  const [numbers, setNumbers] = useState(() => Object.fromEntries(policyFields.map(({ key }) => [key, String(policy[key] ?? "")])));
  const [search, setSearch] = useState("");
  const sources = useMemo(() => {
    const available = new Map<string, AlarmSignal>();
    for (const job of jobs) {
      if (!selected.includes(job.id)) continue;
      const names = job.config.signalMapping ? Object.values(job.config.signalMapping) : job.config.signals;
      for (const signal of names) {
        const value = { datasetId: job.dataset_id, signal };
        available.set(signalKey(value), value);
      }
    }
    return available;
  }, [jobs, selected]);
  const datasetNames = new Map(datasets.map(dataset => [dataset.id, dataset.name]));
  const visibleJobs = jobs.filter(job => `${job.name} ${datasetNames.get(job.dataset_id) || ""} ${job.config.algorithm}`.toLowerCase().includes(search.trim().toLowerCase()));
  const policySources = (label: string, current: AlarmSignal, onChange: (signal: AlarmSignal) => void) => <label>{tr(label)}
    <select value={sources.has(signalKey(current)) ? signalKey(current) : ""} onChange={e => onChange(sources.get(e.target.value) || emptySignal)} required>
      <option value="">{tr("Select a signal")}</option>
      {[...sources].map(([id, value]) => <option key={id} value={id}>{datasetNames.get(value.datasetId) || value.datasetId} · {value.signal}</option>)}
    </select>
  </label>;
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!selected.length || !name.trim()) return;
    const values = Object.fromEntries(policyFields.map(({ key }) => [key, numbers[key] === "" ? null : Number(numbers[key])]));
    onCreate(name.trim(), selected, { ...policy, ...values });
  }
  function addPriority() {
    let next = 1;
    while (policy.priorities.some(item => item.id === `priority-${next}`)) next++;
    setPolicy({ ...policy, priorities: [...policy.priorities, { id: `priority-${next}`, label: "" }] });
  }
  function removePriority(id: string) {
    const priorities = policy.priorities.filter(item => item.id !== id);
    setPolicy({ ...policy, priorities, defaultPriority: policy.defaultPriority === id ? priorities[0].id : policy.defaultPriority,
      mappings: policy.mappings.map(item => item.priority === id ? { ...item, priority: undefined } : item) });
  }
  function movePriority(index: number, next: number) {
    const priorities = [...policy.priorities];
    [priorities[index], priorities[next]] = [priorities[next], priorities[index]];
    setPolicy({ ...policy, priorities });
  }
  return <form className="ws-panel alarm-setup" onSubmit={submit} onInvalid={event => {
    const disclosure = (event.target as HTMLElement).closest("details");
    if (disclosure) disclosure.open = true;
  }}>
    <div className="alarm-section-heading"><h2>{tr("New alarm session")}</h2><button className="ws-outlined" type="button" onClick={onCancel}>{tr("Cancel")}</button></div>
    <label>{tr("Session name")}<input autoFocus required maxLength={160} value={name} onChange={e => setName(e.target.value)} /></label>
    <fieldset>
      <legend>{tr("Saved analysis results")}</legend>
      <label>{tr("Find analyses")}<input type="search" value={search} onChange={e => setSearch(e.target.value)} /></label>
      <div className="alarm-pick-list">
        {visibleJobs.map(job => <label key={job.id}><input type="checkbox" checked={selected.includes(job.id)} onChange={e => {
          const checked = e.target.checked;
          setSelected(ids => checked ? [...ids, job.id] : ids.filter(id => id !== job.id));
        }} /><span><strong>{job.name}</strong><small>{datasetNames.get(job.dataset_id) || job.dataset_id} · {tr(algorithms[job.config.algorithm] || job.config.algorithm)} · {dateLabel(job.created_at)}</small></span></label>)}
      </div>
      {visibleJobs.length === 0 && <p>{tr(jobs.length ? "No analyses match the search." : "Run an analysis in this workspace to generate alarms.")}</p>}
      <p className="ws-muted">{tr("{0} analyses selected", { 0: selected.length })}</p>
    </fieldset>
    <fieldset>
      <legend>{tr("Alarm policy")}</legend>
      <div className="ws-form-grid ws-three">
        {policyFields.map(({ key, label, min, step }) => <label key={key}>{tr(label)}<input type="number" min={min} step={step} required={key !== "escalationSeconds"} value={numbers[key]} onChange={e => setNumbers({ ...numbers, [key]: e.target.value })} /></label>)}
      </div>
      <label className="alarm-check"><input type="checkbox" checked={policy.groupByEquipment} onChange={e => setPolicy({ ...policy, groupByEquipment: e.target.checked })} />{tr("Allow correlation through shared equipment")}</label>
      <p className="ws-muted">{tr("Persistence limits affect grouping and escalation. Every detector alarm stays in the session.")}</p>
      <details>
        <summary>{tr("Priorities and signal mappings")}</summary>
        <p className="ws-muted">{tr("List priorities from highest to lowest. Assign them using engineering knowledge of signals and equipment.")}</p>
        <div className="alarm-priorities">
          {policy.priorities.map((item, index) => <div key={item.id} className="alarm-policy-row">
            <label>{tr("Priority {0}", { 0: index + 1 })}<input required maxLength={200} value={item.label} onChange={e => setPolicy({ ...policy, priorities: policy.priorities.map(value => value.id === item.id ? { ...value, label: e.target.value } : value) })} /></label>
            <button type="button" className="ws-outlined" aria-label={tr("Raise priority {0}", { 0: index + 1 })} disabled={index === 0} onClick={() => movePriority(index, index - 1)}>↑</button>
            <button type="button" className="ws-outlined" aria-label={tr("Lower priority {0}", { 0: index + 1 })} disabled={index + 1 === policy.priorities.length} onClick={() => movePriority(index, index + 1)}>↓</button>
            <button type="button" className="ws-outlined" disabled={policy.priorities.length === 1} onClick={() => removePriority(item.id)}>{tr("Remove")}</button>
          </div>)}
        </div>
        <div className="alarm-policy-row">
          <button type="button" className="ws-outlined" onClick={addPriority}>{tr("Add priority")}</button>
          <label>{tr("Default priority")}<select value={policy.defaultPriority} onChange={e => setPolicy({ ...policy, defaultPriority: e.target.value })}>
            {policy.priorities.map(({ id }) => <option key={id} value={id}>{priorityLabel(policy, id)}</option>)}
          </select></label>
        </div>
        <div className="alarm-policy-mappings">
          {policy.mappings.map((mapping, index) => {
            function update(patch: Partial<typeof mapping>) {
              setPolicy({ ...policy, mappings: policy.mappings.map((value, at) => index === at ? { ...value, ...patch } : value) });
            }
            return <div className="alarm-policy-row" key={index}>
              {policySources("Signal", mapping, update)}
              <label>{tr("Equipment")}<input maxLength={200} value={mapping.equipment || ""} onChange={e => update({ equipment: e.target.value })} /></label>
              <label>{tr("Priority")}<select value={mapping.priority || ""} onChange={e => update({ priority: e.target.value || undefined })}>
                <option value="">{tr("Default priority")}</option>{policy.priorities.map(({ id }) => <option key={id} value={id}>{priorityLabel(policy, id)}</option>)}
              </select></label>
              <button type="button" className="ws-outlined" onClick={() => setPolicy({ ...policy, mappings: policy.mappings.filter((_, i) => i !== index) })}>{tr("Remove")}</button>
            </div>;
          })}
        </div>
        <button type="button" className="ws-outlined" disabled={!sources.size} onClick={() => setPolicy({ ...policy, mappings: [...policy.mappings, emptySignal] })}>{tr("Map a signal")}</button>
      </details>
      <details>
        <summary>{tr("Explicit signal relationships")}</summary>
        {policy.relationships.map((pair, index) => <div className="alarm-policy-row" key={index}>
          {policySources("First signal", pair.left, left => setPolicy({ ...policy, relationships: policy.relationships.map((value, i) => i === index ? { ...value, left } : value) }))}
          {policySources("Related signal", pair.right, right => setPolicy({ ...policy, relationships: policy.relationships.map((value, i) => i === index ? { ...value, right } : value) }))}
          <button type="button" className="ws-outlined" onClick={() => setPolicy({ ...policy, relationships: policy.relationships.filter((_, i) => i !== index) })}>{tr("Remove")}</button>
        </div>)}
        <button type="button" className="ws-outlined" disabled={sources.size < 2} onClick={() => setPolicy({ ...policy, relationships: [...policy.relationships, { left: emptySignal, right: emptySignal }] })}>{tr("Add relationship")}</button>
      </details>
    </fieldset>
    <button className="ws-primary" disabled={busy || !selected.length || !name.trim()}>{tr(busy ? "Generating alarm session…" : "Generate and save timeline")}</button>
  </form>;
}
