import { getLocale, t as tr } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { useId, useMemo, useState, type FormEvent } from "react";
import { algorithmParameters } from "./AlgorithmControls";
import { NumericFields, NumericInput, signalName } from "./ResilienceScenario";
import { dateLabel, number } from "./types";
import type { Campaign, CampaignSpec, CampaignSummary, CaseSummary, Catalog, Detector, Model, Scenario } from "./resilienceTypes";

type Axis = { id: number; path: string; values: string; min: number; max: number };
type AxisOption = { path: string; label: string; min: number; max: number; values: string; discrete?: boolean };

function axisOptions(scenario: Scenario, model: Model, mode: CampaignSpec["mode"]): AxisOption[] {
  const fields: AxisOption[] = [
    { path: "faults", label: tr("Fault combinations"), min: 0, max: 1, values: JSON.stringify([[], ...scenario.faults.map(fault => [fault]), ...(scenario.faults.length > 1 ? [scenario.faults] : [])]), discrete: true },
    { path: "measurement.noise", label: tr("Level sensor noise (m)"), min: 0, max: .02, values: "[0.002, 0.01, 0.02]" },
    { path: "measurement.missing_fraction", label: tr("Random missing fraction"), min: 0, max: .3, values: "[0, 0.1, 0.3]" },
    { path: "measurement.physical_noise", label: tr("Relative inlet disturbance"), min: 0, max: .05, values: "[0, 0.02, 0.05]" },
    { path: "seed", label: tr("Scenario seed"), min: 100, max: 999, values: "[100, 101, 102]" },
    ...(["initial", "parameters"] as const).flatMap(group =>
      model[group].flatMap(field => {
        const nominal = field.default ?? field.min;
        const min = Math.max(field.min, nominal * .8), max = Math.min(field.max, nominal * 1.2);
        const values = JSON.stringify([...new Set([min, nominal, max])]);
        return [
          { path: `${group}.${field.key}`, label: tr(field.label), min, max, values },
          { path: `detector.training.${group}.${field.key}`, label: `${tr("Reference model")} · ${tr(field.label)}`, min, max, values },
        ];
      })),
    ...scenario.faults.flatMap(fault => {
      const recovery = fault.recovery ?? scenario.duration;
      const onsetMin = fault.onset * .75;
      const onsetMax = Math.min((fault.onset + recovery) / 2, fault.onset * 1.25 + scenario.sample_interval);
      const remaining = scenario.duration - fault.onset;
      const durationMin = remaining * .25, durationMax = remaining * .6;
      return [
        { path: `faults.${fault.id}.severity`, label: `${fault.id} · ${tr("Severity (0–1)")}`, min: .1, max: 1, values: "[0.25, 0.5, 0.75]" },
        { path: `faults.${fault.id}.onset`, label: `${fault.id} · ${tr("Fault onset (s)")}`, min: onsetMin, max: onsetMax,
          values: JSON.stringify([...new Set([onsetMin, fault.onset, onsetMax])]) },
        { path: `faults.${fault.id}.recovery`, label: `${fault.id} · ${tr("Recovery time (s)")}`, min: fault.onset + remaining * .6, max: scenario.duration,
          values: JSON.stringify([fault.onset + remaining * .6, scenario.duration]) },
        { path: `faults.${fault.id}.duration`, label: `${fault.id} · ${tr("Fault duration (s)")}`, min: durationMin, max: durationMax,
          values: JSON.stringify([durationMin, durationMax]) },
      ];
    }),
  ];
  return mode === "search" ? fields.filter(field => !field.discrete && field.min < field.max && !field.path.startsWith("detector.")) : fields;
}

function DetectorEditor({ detector, catalog, model, visibleSignals, onChange }: {
  detector: Detector;
  catalog: Catalog;
  model: Model;
  visibleSignals: string[];
  onChange: (detector: Detector) => void;
}) {
  const signals = detector.signals ?? [];
  const training = detector.training ?? {};
  return <>
    <div className="ws-form-grid ws-three">
      <label>{tr("Detection algorithm")}<select value={detector.algorithm} onChange={event => onChange({ ...detector, algorithm: event.target.value })}>
        {Object.entries(catalog.algorithms).map(([id, name]) => <option key={id} value={id} disabled={id.includes("pca") && signals.length < 2}>{tr(name)}</option>)}
      </select></label>
      <NumericInput label={tr("Calibration alpha")} min={.000001} max={.499999} value={detector.alpha ?? .01} onChange={alpha => onChange({ ...detector, alpha: alpha ?? .01 })} />
      <NumericInput label={tr("Minimum observed fraction")} min={.000001} max={1} value={detector.minCoverage ?? .9} onChange={minCoverage => onChange({ ...detector, minCoverage: minCoverage ?? .9 })} />
      <NumericInput label={tr("Alarm persistence (samples)")} min={1} integer value={detector.persistence ?? 3} onChange={persistence => onChange({ ...detector, persistence: persistence ?? 3 })} />
      {algorithmParameters(detector.algorithm).map(([key, label, fallback, min, max]) => <NumericInput key={key} label={tr(label)} min={min} max={max} integer={key === "lags" || key === "window"}
        value={typeof detector[key as keyof Detector] === "number" ? detector[key as keyof Detector] as number : fallback}
        onChange={value => onChange({ ...detector, [key]: value ?? fallback })} />)}
    </div>
    <fieldset><legend>{tr("Detector input signals")}</legend><div className="resilience-options">
      {model.signals.filter(signal => visibleSignals.includes(signal.key)).map(signal => {
        const selected = signals.includes(signal.key);
        return <label key={signal.key}><input type="checkbox" checked={selected} disabled={selected && signals.length <= (detector.algorithm.includes("pca") ? 2 : 1)}
          onChange={event => onChange({ ...detector, signals: event.target.checked ? [...signals, signal.key] : signals.filter(key => key !== signal.key),
            requiredSignals: (detector.requiredSignals ?? []).filter(key => event.target.checked || key !== signal.key) })} />{signalName(signal)}</label>;
      })}
    </div></fieldset>
    <details><summary>{tr("Independent healthy reference and model mismatch")}</summary>
      <div className="ws-form-grid ws-three">
        <NumericInput label={tr("Reference seed")} min={0} max={2147483647} integer value={training.seed ?? 14071} onChange={seed => onChange({ ...detector, training: { ...training, seed: seed ?? 14071 } })} />
        <NumericInput label={tr("Reference noise (m)")} min={0} max={.1} value={training.noise ?? .002} onChange={noise => onChange({ ...detector, training: { ...training, noise: noise ?? .002 } })} />
      </div>
      <NumericFields fields={model.initial} values={training.initial ?? {}} onChange={(key, value) => {
        if (value !== null) onChange({ ...detector, training: { ...training, initial: { ...training.initial, [key]: value } } });
      }} />
      <NumericFields fields={model.parameters} values={training.parameters ?? {}} onChange={(key, value) => {
        if (value !== null) onChange({ ...detector, training: { ...training, parameters: { ...training.parameters, [key]: value } } });
      }} />
      <button type="button" className="ws-outlined" onClick={() => onChange({ ...detector, training: { seed: training.seed, noise: training.noise } })}>{tr("Restore nominal reference model")}</button>
    </details>
  </>;
}

export function CampaignForm({ catalog, scenario, onStart, busy }: {
  catalog: Catalog;
  scenario: Scenario;
  onStart: (spec: CampaignSpec) => void;
  busy: boolean;
}) {
  const titleId = useId();
  const [mode, setMode] = useState<CampaignSpec["mode"]>("grid");
  const [customBenchmark, setCustomBenchmark] = useState(false);
  const [name, setName] = useState("");
  const [detectors, setDetectors] = useState(catalog.default_detectors.map((detector, index) => ({ id: index, detector })));
  const [nextDetectorId, setNextDetectorId] = useState(catalog.default_detectors.length);
  const [axes, setAxes] = useState<Axis[]>([]);
  const [nextAxisId, setNextAxisId] = useState(0);
  const [seed, setSeed] = useState(62043);
  const [budget, setBudget] = useState(12);
  const [objective, setObjective] = useState(catalog.objectives[0]);
  const [error, setError] = useState("");
  const benchmark = mode === "benchmark", search = mode === "search";
  const model = catalog.models.find(item => item.id === scenario.model_id) ?? catalog.models[0];
  const choices = useMemo(() => axisOptions(scenario, model, mode), [scenario, model, mode]);
  const selectedDetectors = (search ? detectors.slice(0, 1) : detectors).map(item => ({
    ...item.detector,
    signals: (item.detector.signals ?? scenario.measurement.signals).filter(key => benchmark || scenario.measurement.signals.includes(key)),
    requiredSignals: (item.detector.requiredSignals ?? []).filter(key => benchmark || scenario.measurement.signals.includes(key)),
  }));
  const available = choices.filter(choice => !axes.some(axis => axis.path === choice.path));
  function parseGrid(): { path: string; values: unknown[] }[] {
    return axes.map(axis => {
      const values: unknown = JSON.parse(axis.values);
      if (!Array.isArray(values) || !values.length) throw new Error("Each sweep axis needs a nonempty JSON array.");
      return { path: axis.path, values };
    });
  }
  let caseCount = selectedDetectors.length;
  if (search) caseCount = budget;
  else {
    try { caseCount *= parseGrid().reduce((count, axis) => count * axis.values.length, 1); }
    catch { caseCount = 0; }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const title = name.trim() || tr(benchmark ? "Fixed resilience benchmark" : search ? "Failure search" : "Resilience campaign");
    if (benchmark) { onStart({ name: title, mode, detectors: customBenchmark ? selectedDetectors : undefined }); return; }
    try {
      if (search && !axes.length) throw new Error("Add a parameter range to start a failure search.");
      if (axes.some(axis => !choices.some(choice => choice.path === axis.path))) throw new Error("A sweep axis refers to a removed fault. Select an available parameter.");
      if (axes.some(axis => axis.path === "faults") && axes.some(axis => axis.path.startsWith("faults."))) throw new Error("Run fault combinations and individual event sweeps as separate campaigns.");
      if (search && axes.some(axis => axis.min >= axis.max)) throw new Error("Each search maximum must exceed its minimum.");
      if (caseCount > catalog.max_cases) throw new Error("Reduce the campaign to the supported case limit.");
      const spec: CampaignSpec = { name: title, mode, scenario, detectors: selectedDetectors,
        axes: search ? axes.map(({ path, min, max }) => ({ path, min, max })) : parseGrid() };
      if (search) Object.assign(spec, { seed, budget, objective });
      onStart(spec);
    } catch (caught) { setError(caught instanceof SyntaxError ? "Enter a valid JSON array for each sweep axis." : caught instanceof Error ? caught.message : String(caught)); }
  }
  return <form className="ws-panel resilience-campaign" onSubmit={submit} aria-labelledby={titleId}>
    <h2 id={titleId}>{tr("Run a campaign")}</h2>
    <div className="ws-form-grid">
      <label>{tr("Campaign mode")}<select value={mode} onChange={event => {
        setMode(event.target.value as CampaignSpec["mode"]);
        setAxes([]);
        setError("");
      }}><option value="grid">{tr("Scenario grid")}</option><option value="search">{tr("Failure search")}</option><option value="benchmark">{tr("Fixed resilience benchmark")}</option></select></label>
      <label>{tr("Campaign name")}<input value={name} maxLength={160} onChange={event => setName(event.target.value)} placeholder={tr("Optional")} /></label>
    </div>
    {benchmark ? <><p className="ws-notice">{tr("Benchmark {0} runs fixed healthy, single-fault, overlapping and acquisition-fault cases with held-out seeds.", { 0: catalog.benchmark_version })}
      {" "}{[...new Set(catalog.benchmark_detectors.map(detector => tr(catalog.algorithms[detector.algorithm] ?? detector.algorithm)))].join(" · ")}
    </p><div className="resilience-options"><label><input type="checkbox" checked={customBenchmark} onChange={event => setCustomBenchmark(event.target.checked)} />{tr("Customize benchmark detectors")}</label></div></> : <>
      <p className="ws-muted">{tr("The campaign uses the current composer settings. Every detector uses an independent healthy reference.")}</p>
      {search && <div className="ws-form-grid ws-three">
        <label>{tr("Search objective")}<select value={objective} onChange={event => setObjective(event.target.value)}>
          {catalog.objectives.map(item => <option key={item} value={item}>{tr(`resilience objective ${item}`)}</option>)}
        </select></label>
        <NumericInput label={tr("Search seed")} min={0} max={2147483647} integer value={seed} onChange={value => setSeed(value ?? 62043)} />
        <NumericInput label={tr("Search case budget")} min={1} max={catalog.max_search_cases} integer value={budget} onChange={value => setBudget(value ?? 12)} />
      </div>}
      <div className="ws-section-heading"><h3>{tr(search ? "Search ranges" : "Sweep axes")}</h3>
        <button type="button" className="ws-outlined" disabled={!available.length} onClick={() => {
          const { path, values, min, max } = available[0];
          setAxes(previous => [...previous, { id: nextAxisId, path, values, min, max }]);
          setNextAxisId(nextAxisId + 1);
        }}>{tr(search ? "Add range" : "Add axis")}</button>
      </div>
      {axes.map(axis => {
        function edit(values: Partial<Axis>) { setAxes(previous => previous.map(item => item.id === axis.id ? { ...item, ...values } : item)); }
        return <fieldset className="resilience-sweep-axis" key={axis.id}>
          <label>{tr("Parameter")}<select value={axis.path} onChange={event => {
            const choice = choices.find(item => item.path === event.target.value);
            if (choice) edit({ path: choice.path, values: choice.values, min: choice.min, max: choice.max });
          }}>
            {!choices.some(choice => choice.path === axis.path) && <option value={axis.path}>{axis.path}</option>}
            {choices.filter(choice => choice.path === axis.path || available.includes(choice)).map(choice => <option key={choice.path} value={choice.path}>{choice.label}</option>)}
          </select></label>
          {search ? <div className="ws-form-grid">
            <NumericInput label={tr("Minimum")} value={axis.min} integer={axis.path === "seed"} onChange={min => edit({ min: min ?? 0 })} />
            <NumericInput label={tr("Maximum")} value={axis.max} integer={axis.path === "seed"} onChange={max => edit({ max: max ?? 0 })} />
          </div> : axis.path === "faults" ? <details><summary>{tr("Healthy, single faults and all faults together")}</summary>
            <label>{tr("Fault combinations (JSON event lists)")}<textarea rows={4} value={axis.values} onChange={event => edit({ values: event.target.value })} /></label>
            <button type="button" className="ws-outlined" onClick={() => edit({ values: choices.find(choice => choice.path === "faults")?.values })}>{tr("Use current fault schedule")}</button>
          </details> : <label>{tr("Values (JSON array)")}<input value={axis.values} onChange={event => edit({ values: event.target.value })} required /></label>}
          <button type="button" className="ws-outlined" onClick={() => setAxes(previous => previous.filter(item => item.id !== axis.id))}>{tr("Remove axis")}</button>
        </fieldset>;
      })}
    </>}
    {(!benchmark || customBenchmark) && <>
      <div className="ws-section-heading"><h3>{tr("Detector configurations")}</h3>
        {!search && <button type="button" className="ws-outlined" disabled={detectors.length >= (benchmark ? catalog.benchmark_detectors.length : Object.keys(catalog.algorithms).length)} onClick={() => {
          setDetectors(previous => [...previous, { id: nextDetectorId, detector: catalog.default_detectors[0] }]);
          setNextDetectorId(nextDetectorId + 1);
        }}>{tr("Add detector")}</button>}
      </div>
      {(search ? detectors.slice(0, 1) : detectors).map(({ id }, index) => <fieldset className="resilience-detector" key={id}>
        <legend>{tr("Detector {0}", { 0: index + 1 })}</legend>
        <DetectorEditor detector={selectedDetectors[index]} catalog={catalog} model={model} visibleSignals={benchmark ? model.signals.map(signal => signal.key) : scenario.measurement.signals}
          onChange={detector => setDetectors(previous => previous.map(item => item.id === id ? { id, detector } : item))} />
        {!search && detectors.length > 1 && <button type="button" className="ws-outlined" onClick={() => setDetectors(previous => previous.filter(item => item.id !== id))}>{tr("Remove detector")}</button>}
      </fieldset>)}
    </>}
    {error && <p role="alert" className="ws-error">{errorMessage(error)}</p>}
    <div className="resilience-actions">
      {!benchmark && <p className="ws-muted">{tr("{0} planned cases · limit {1}", { 0: caseCount, 1: catalog.max_cases })}</p>}
      <button type="submit" className="ws-primary" disabled={busy || !benchmark && caseCount > catalog.max_cases}>{tr("Start campaign")}</button>
    </div>
  </form>;
}

export function CampaignList({ campaigns, activeId, onOpen }: {
  campaigns: CampaignSummary[];
  activeId?: string;
  onOpen: (id: string) => void;
}) {
  return <label>{tr("Saved campaigns")}<select value={activeId ?? ""} onChange={event => onOpen(event.target.value)}>
    <option value="">{tr("Choose a campaign")}</option>
    {campaigns.map(campaign => <option key={campaign.id} value={campaign.id}>{campaign.name} · {dateLabel(campaign.created_at)} · {tr(campaign.status)}</option>)}
  </select></label>;
}

function detectorKey(detector: Detector) {
  function ordered(value: unknown): unknown {
    if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, ordered(item)]));
  }
  return JSON.stringify(ordered(detector));
}

function campaignGroups(cases: CaseSummary[]) {
  const groups = new Map<string, { id: string; phase: string; detector: Detector; faults: number; events: number; detected: number; covered: number; runs: number }>();
  for (const { metrics, detector, phase } of cases) {
    if (!metrics) continue;
    const faults = Math.min(2, metrics.totalEvents);
    const key = JSON.stringify([phase, detectorKey(detector), faults]);
    const group = groups.get(key) ?? { id: key, phase, detector, faults, events: 0, detected: 0, covered: 0, runs: 0 };
    group.events += metrics.totalEvents;
    group.detected += metrics.detectedEvents;
    group.covered += metrics.coverage;
    group.runs++;
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => a.phase.localeCompare(b.phase) || a.detector.algorithm.localeCompare(b.detector.algorithm) || a.faults - b.faults);
}

export function fraction(value: number | null | undefined) {
  return value == null ? "—" : new Intl.NumberFormat(getLocale(), { style: "percent", maximumFractionDigits: 1 }).format(value);
}

export function caseName(name: string) {
  const generated = /^(Search|Grid) (\d+)$/.exec(name);
  const key = `resilience case ${name}`;
  const label = tr(key);
  return generated ? tr(generated[1] + " case {0}", { 0: generated[2] }) : label === key ? name : label;
}

export function CampaignResults({ campaign, catalog, report, selected, onSelect }: {
  campaign: Campaign;
  catalog: Catalog;
  report: string;
  selected?: string;
  onSelect: (id: string) => void;
}) {
  const [filter, setFilter] = useState("all");
  const [phase, setPhase] = useState("all");
  const groups = campaignGroups(campaign.cases);
  const detectorIds = new Map([...new Set(campaign.cases.map(item => detectorKey(item.detector)))].map((key, index) => [key, index + 1]));
  const detectorName = (detector: Detector) => `${tr(catalog.algorithms[detector.algorithm] ?? detector.algorithm)} · #${detectorIds.get(detectorKey(detector))}`;
  const phases = [...new Set(campaign.cases.map(item => item.phase))];
  const running = campaign.status === "queued" || campaign.status === "running";
  const cases = campaign.cases.filter(item => (phase === "all" || item.phase === phase) &&
    (filter === "all" || filter === "missed" && Boolean(item.metrics?.missedEvents) || filter === "failed" && item.status === "failed"));
  const searchScore = (item: CaseSummary) => item.objective ? item.metrics?.searchScores?.[item.objective] : undefined;
  cases.sort((left, right) => left.phase.localeCompare(right.phase) || (searchScore(right) ?? -Infinity) - (searchScore(left) ?? -Infinity) || left.index - right.index);
  return <section className="ws-panel resilience-campaign-results">
    <div className="ws-section-heading"><h2>{campaign.name}</h2>
      {!running && campaign.completed > 0 && <a className="ws-link" href={report} target="_blank" rel="noreferrer">{tr("Open campaign report ↗")}</a>}
    </div>
    <div className="resilience-progress">
      <progress value={campaign.completed} max={Math.max(1, campaign.total)} aria-label={tr("Campaign progress")} />
      <p role="status">{tr(campaign.status)} · {tr("{0} / {1} cases finished", { 0: campaign.completed, 1: campaign.total })}</p>
    </div>
    {campaign.error && <p role="alert" className="ws-error">{errorMessage(campaign.error)}</p>}
    {groups.length > 0 && <details open className="resilience-summary">
      <summary>{tr("Fault combination comparison")}</summary>
      <p className="ws-muted">{tr("Detection rate uses individually matched events. Coverage is the mean detector availability across runs.")}</p>
      {groups.map(group => <div className="resilience-summary-row" key={group.id}>
        <div><strong>{detectorName(group.detector)}</strong><small>{group.detector.signals?.join(", ")}</small><small>{tr(group.phase)} · {tr(["Healthy controls", "Single fault", "Multiple faults"][group.faults])} · {tr("{0} runs", { 0: group.runs })}</small></div>
        <div><span>{tr("Event detection rate")} {group.events ? fraction(group.detected / group.events) : "—"}</span>{group.events > 0 && <meter min={0} max={1} value={group.detected / group.events} aria-label={tr("Event detection rate")} />}</div>
        <div><span>{tr("Coverage")} {fraction(group.covered / group.runs)}</span><meter min={0} max={1} value={group.covered / group.runs} aria-label={tr("Coverage")} /></div>
      </div>)}
    </details>}
    <div className="ws-form-grid">
      <label>{tr("Case filter")}<select value={filter} onChange={event => setFilter(event.target.value)}>
        <option value="all">{tr("All cases")}</option><option value="missed">{tr("Missed events")}</option><option value="failed">{tr("Failed cases")}</option>
      </select></label>
      {phases.length > 1 && <label>{tr("Campaign phase")}<select value={phase} onChange={event => setPhase(event.target.value)}>
        <option value="all">{tr("All phases")}</option>{phases.map(item => <option key={item} value={item}>{tr(item)}</option>)}
      </select></label>}
    </div>
    <div className="ws-table-scroll resilience-results-table"><table>
      <thead><tr>{["Case", "Detection algorithm", "Events matched", "Mean delay (s)", "Coverage", "Healthy alarms", "Search objective score", "Runtime (ms)", "Status"].map(label => <th key={label}>{tr(label)}</th>)}</tr></thead>
      <tbody>{cases.map(item => <tr key={item.id} className={selected === item.id ? "resilience-case-selected" : undefined}>
        <td><button className="ws-link" type="button" aria-pressed={selected === item.id} onClick={() => onSelect(item.id)}>{caseName(item.name)}</button><small>{tr(item.phase)} · {tr(item.family)}</small></td>
        <td>{detectorName(item.detector)}<small>{item.detector.signals?.join(", ")}</small></td>
        <td className={item.metrics?.missedEvents ? "ws-coral" : undefined}>{item.metrics ? `${item.metrics.detectedEvents} / ${item.metrics.totalEvents}` : "—"}</td>
        <td>{item.metrics?.meanDelay == null ? "—" : number(item.metrics.meanDelay)}</td>
        <td>{fraction(item.metrics?.coverage)}</td><td>{fraction(item.metrics?.normal?.alarmFraction)}</td>
        <td>{searchScore(item) == null ? "—" : number(searchScore(item)!)}</td>
        <td>{item.runtime_ms == null ? "—" : number(item.runtime_ms)}</td>
        <td>{tr(item.status)}{item.error && <small title={errorMessage(item.error)}>{errorMessage(item.error)}</small>}</td>
      </tr>)}</tbody>
    </table></div>
    {!cases.length && <p className="ws-muted">{tr("No cases match this view.")}</p>}
  </section>;
}
