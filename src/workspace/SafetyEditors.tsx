import { t as tr } from "../i18n";
import { signalLabel, type CatalogSignal, type Dataset } from "./types";
import { forecastParameters, uncertaintyParameters, type ForecastOptions, type ForecastParameter, type SafetyDefinition, type SafetyKind, type UncertaintyParameter } from "./safetyTypes";

const boundaryFields = ["lower", "upper", "warningLower", "warningUpper"] as const;
const policyFields = ["dwellSeconds", "hysteresis", "maxGapSeconds"] as const;
type NumericDefinitionField = typeof boundaryFields[number] | typeof policyFields[number];
const fieldLabels: Record<NumericDefinitionField, string> = {
  lower: "Critical lower limit", upper: "Critical upper limit", warningLower: "Lower warning boundary", warningUpper: "Upper warning boundary",
  dwellSeconds: "Dwell (s)", hysteresis: "Hysteresis", maxGapSeconds: "Maximum observation gap (s)",
};
const kindLabels: Record<SafetyKind, string> = { value: "Value or permitted range", rate: "Rate of change", relationship: "Linear signal relationship" };
export type ConstraintDraft = Omit<SafetyDefinition, NumericDefinitionField | "terms"> & Record<NumericDefinitionField, string> & { terms: { signalId: string; coefficient: string }[] };

const draftNumber = (value: number | null | undefined) => value == null ? "" : String(value);
const optionalNumber = (value: string) => value.trim() === "" ? undefined : Number(value);

export function toConstraintDraft(definition: SafetyDefinition): ConstraintDraft {
  return {
    ...definition, lower: draftNumber(definition.lower), upper: draftNumber(definition.upper),
    warningLower: draftNumber(definition.warningLower), warningUpper: draftNumber(definition.warningUpper),
    dwellSeconds: draftNumber(definition.dwellSeconds), hysteresis: draftNumber(definition.hysteresis), maxGapSeconds: draftNumber(definition.maxGapSeconds),
    terms: definition.terms.map(term => ({ signalId: term.signalId, coefficient: String(term.coefficient ?? 1) })),
  };
}

export function toConstraintDefinition(draft: ConstraintDraft): SafetyDefinition {
  return {
    ...draft, lower: optionalNumber(draft.lower), upper: optionalNumber(draft.upper),
    warningLower: optionalNumber(draft.warningLower), warningUpper: optionalNumber(draft.warningUpper),
    dwellSeconds: optionalNumber(draft.dwellSeconds), hysteresis: optionalNumber(draft.hysteresis), maxGapSeconds: optionalNumber(draft.maxGapSeconds),
    terms: draft.terms.map(term => ({ signalId: term.signalId, coefficient: draft.kind === "relationship" ? Number(term.coefficient) : 1 })),
  };
}

export function newConstraint(signal?: CatalogSignal): ConstraintDraft {
  return toConstraintDraft({ id: crypto.randomUUID(), name: "", kind: "value", unit: signal?.unit || "", terms: [{ signalId: signal?.id || "" }] });
}

function defaultUnit(kind: SafetyKind, unit?: string) {
  const differenceUnit = unit === "°C" || unit === "°F" || unit === "K" ? `Δ${unit}` : unit || "1";
  if (kind === "rate") return `${differenceUnit}/s`;
  return kind === "relationship" && unit ? differenceUnit : unit || "";
}

export function NumericField({ label, value, onChange, min, max, integer, required, placeholder }: {
  label: string; value: string; onChange: (value: string) => void; min?: number; max?: number; integer?: boolean; required?: boolean; placeholder?: string;
}) {
  return <label>{label}<input type="number" step={integer ? 1 : "any"} value={value} min={min} max={max} required={required}
    placeholder={placeholder} onChange={event => onChange(event.target.value)} /></label>;
}

export function ConstraintEditor({ draft, index, signals, onChange, onRemove }: {
  draft: ConstraintDraft; index: number; signals: CatalogSignal[]; onChange: (next: ConstraintDraft) => void; onRemove: () => void;
}) {
  const primary = signals.find(signal => signal.id === draft.terms[0]?.signalId);
  const alternative = signals.find(signal => !draft.terms.some(term => term.signalId === signal.id));
  function changeKind(kind: SafetyKind) {
    const terms = kind === "relationship"
      ? [...draft.terms, { signalId: alternative?.id || "", coefficient: "-1" }]
      : draft.terms.slice(0, 1).map(term => ({ ...term, coefficient: "1" }));
    onChange({ ...draft, kind, terms, unit: defaultUnit(kind, primary?.unit), absolute: kind === "rate" });
  }
  function changeTerm(index: number, term: ConstraintDraft["terms"][number]) {
    const terms = draft.terms.map((previous, position) => position === index ? term : previous);
    const autoUnit = index === 0 && draft.unit === defaultUnit(draft.kind, primary?.unit);
    onChange({ ...draft, terms, unit: autoUnit ? defaultUnit(draft.kind, signals.find(signal => signal.id === term.signalId)?.unit) : draft.unit });
  }
  return <fieldset className="safety-limit-editor">
    <legend>{tr("Constraint {0}", { 0: index + 1 })}</legend>
    <div className="ws-form-grid safety-fields">
      <label>{tr("Constraint name")}<input maxLength={160} required value={draft.name} onChange={event => onChange({ ...draft, name: event.target.value })} /></label>
      <label>{tr("Constraint type")}<select value={draft.kind} onChange={event => changeKind(event.target.value as SafetyKind)}>
        {(Object.keys(kindLabels) as SafetyKind[]).map(kind => <option key={kind} value={kind} disabled={kind === "relationship" && signals.length < 2}>{tr(kindLabels[kind])}</option>)}
      </select></label>
      <label>{tr("Constraint unit")}<input value={draft.unit} maxLength={40} onChange={event => onChange({ ...draft, unit: event.target.value })}
        placeholder={tr("Use the Signal Catalog unit")} /></label>
      <label>{tr("Equipment (optional)")}<input value={draft.equipment || ""} maxLength={160} onChange={event => onChange({ ...draft, equipment: event.target.value })} /></label>
    </div>
    {draft.terms.map((term, termIndex) => <div className="safety-term" key={termIndex}>
      <label>{draft.kind === "relationship" ? tr("Signal term {0}", { 0: termIndex + 1 }) : tr("Signal")}<select required value={term.signalId}
        onChange={event => changeTerm(termIndex, { ...term, signalId: event.target.value })}>
        <option value="">{tr("Choose a signal")}</option>
        {term.signalId && !signals.some(signal => signal.id === term.signalId) && <option value={term.signalId}>{tr("Unavailable signal")}</option>}
        {signals.map(signal => <option value={signal.id} key={signal.id} disabled={draft.terms.some((other, i) => i !== termIndex && other.signalId === signal.id)}>{signalLabel(signal)}</option>)}
      </select></label>
      {draft.kind === "relationship" && <><NumericField label={tr("Coefficient")} required value={term.coefficient} onChange={coefficient => changeTerm(termIndex, { ...term, coefficient })} />
        {draft.terms.length > 2 && <button type="button" aria-label={tr("Remove signal term {0}", { 0: termIndex + 1 })}
          onClick={() => onChange({ ...draft, terms: draft.terms.filter((_, i) => i !== termIndex) })}>{tr("Remove")}</button>}</>}
    </div>)}
    {draft.kind === "relationship" && <>
      <p className="ws-muted">{tr("The constraint evaluates the sum of weighted signals after unit conversion.")}</p>
      <button type="button" disabled={!alternative} onClick={() => onChange({ ...draft, terms: [...draft.terms, { signalId: alternative?.id || "", coefficient: "1" }] })}>{tr("Add signal term")}</button>
    </>}
    {draft.kind === "rate" && <label className="ws-inline safety-check"><input type="checkbox" checked={Boolean(draft.absolute)} onChange={event => onChange({ ...draft, absolute: event.target.checked })} />{tr("Use the absolute rate")}</label>}
    <div className="ws-form-grid safety-fields">{boundaryFields.map(field => <NumericField key={field} label={tr(fieldLabels[field])} value={draft[field]}
      required={field === "upper" && !draft.lower} onChange={value => onChange({ ...draft, [field]: value })} />)}</div>
    <details className="safety-policy"><summary>{tr("Dwell, hysteresis and observation gaps")}</summary>
      <div className="ws-form-grid safety-fields">{policyFields.map(field => <NumericField key={field} label={tr(fieldLabels[field])} value={draft[field]}
        min={field === "maxGapSeconds" ? Number.MIN_VALUE : 0} onChange={value => onChange({ ...draft, [field]: value })} />)}</div>
      <p>{tr("Dwell requires continuous observed evidence. Hysteresis is measured in the constraint unit. Leave the maximum gap blank to use the dataset sampling rule.")}</p>
    </details>
    <button type="button" className="ws-danger" onClick={onRemove}>{tr("Remove constraint")}</button>
  </fieldset>;
}

const optionFields = ["asOf", "horizonSeconds", "stepSeconds", "maxObservationAgeSeconds", "pumpCommand", "valveOpening", "leakCoefficient", "samples", "seed"] as const;
type OptionField = typeof optionFields[number];
export type ForecastDraft = Record<OptionField, string> & {
  enabled: boolean; mode: "hold" | "override"; ranges: Partial<Record<UncertaintyParameter, [string, string]>>; parameters: Partial<Record<ForecastParameter, string>>;
};
export const tankSignalLabels: Record<string, [string, string]> = {
  level1: ["Tank 1 level", "m"], level2: ["Tank 2 level", "m"], inlet: ["Inlet flow", "m³/s"],
  transfer: ["Inter-tank flow (signed)", "m³/s"], outlet: ["Outlet delivery flow", "m³/s"],
  pump: ["Pump command", "%"], valve: ["Connection valve opening", "fraction"],
};
export const uncertaintyLabels: Record<UncertaintyParameter, [string, string]> = {
  level1: ["Tank 1 level", "m"], level2: ["Tank 2 level", "m"], pumpRateFraction: ["Nominal pump flow", "fraction"],
  connectionFraction: ["Connection discharge coefficient", "fraction"], outletFraction: ["Outlet discharge coefficient", "fraction"],
  pumpCommand: ["Pump command", "pp"], valveOpening: ["Connection valve opening", "fraction"], outletValve: ["Outlet valve opening", "fraction"],
  leakCoefficient: ["Leak discharge coefficient", "m^(5/2)/s"],
};
const uncertaintyBounds: Record<UncertaintyParameter, [number, number]> = {
  level1: [-10, 10], level2: [-10, 10], pumpRateFraction: [-1, 1], connectionFraction: [-1, 1], outletFraction: [-1, 1],
  pumpCommand: [-150, 150], valveOpening: [-1, 1], outletValve: [-1, 1], leakCoefficient: [-.1, .1],
};
const nominalFields: Record<ForecastParameter, [string, string, number, number]> = {
  area1: ["Tank 1 area", "m²", .1, 10], area2: ["Tank 2 area", "m²", .1, 10], pumpRate: ["Nominal pump flow", "m³/s", 0, .2],
  connection: ["Connection discharge coefficient", "m^(5/2)/s", .001, .2], outlet: ["Outlet discharge coefficient", "m^(5/2)/s", .001, .2],
  outletValve: ["Outlet valve opening", "fraction", .01, 1], tankHeight: ["Overflow height", "m", .1, 10],
  integrationStep: ["Maximum integration step", "s", .005, .25],
};
export function toForecastDraft(options?: ForecastOptions | null): ForecastDraft {
  return {
    enabled: Boolean(options), mode: options?.input?.mode || "hold", asOf: draftNumber(options?.asOf),
    horizonSeconds: draftNumber(options?.horizonSeconds ?? 60), stepSeconds: draftNumber(options?.stepSeconds ?? .2),
    maxObservationAgeSeconds: draftNumber(options?.maxObservationAgeSeconds), pumpCommand: draftNumber(options?.input?.pumpCommand),
    valveOpening: draftNumber(options?.input?.valveOpening), leakCoefficient: draftNumber(options?.input?.leakCoefficient),
    samples: draftNumber(options?.uncertainty?.samples ?? 0), seed: draftNumber(options?.uncertainty?.seed ?? 1),
    ranges: Object.fromEntries(Object.entries(options?.uncertainty?.ranges || {}).map(([key, [lower, upper]]) => [key, [String(lower), String(upper)]])),
    parameters: Object.fromEntries(Object.entries(options?.parameters || {}).map(([key, value]) => [key, String(value)])),
  };
}
export function toForecastOptions(draft: ForecastDraft): ForecastOptions | undefined {
  if (!draft.enabled) return;
  return {
    asOf: optionalNumber(draft.asOf), horizonSeconds: optionalNumber(draft.horizonSeconds), stepSeconds: optionalNumber(draft.stepSeconds),
    maxObservationAgeSeconds: optionalNumber(draft.maxObservationAgeSeconds),
    input: { mode: draft.mode, leakCoefficient: optionalNumber(draft.leakCoefficient), ...(draft.mode === "override" && { pumpCommand: optionalNumber(draft.pumpCommand), valveOpening: optionalNumber(draft.valveOpening) }) },
    parameters: Object.fromEntries(Object.entries(draft.parameters).filter(([, value]) => value !== "").map(([key, value]) => [key, Number(value)])),
    uncertainty: { samples: optionalNumber(draft.samples), seed: optionalNumber(draft.seed),
      ranges: Object.fromEntries(Object.entries(draft.ranges).map(([key, [lower, upper]]) => [key, [Number(lower), Number(upper)]])) },
  };
}

export function ForecastEditor({ draft, dataset, onChange }: { draft: ForecastDraft; dataset: Dataset; onChange: (next: ForecastDraft) => void }) {
  const set = (field: OptionField, value: string) => onChange({ ...draft, [field]: value });
  const time = dataset.metadata.time;
  return <fieldset className="safety-forecast-editor">
    <legend>{tr("Coupled-tank forecast")}</legend>
    <label className="ws-inline safety-check"><input type="checkbox" checked={draft.enabled} onChange={event => onChange({ ...draft, enabled: event.target.checked })} />{tr("Include a forecast")}</label>
    {draft.enabled && <>
      <div className="ws-form-grid safety-fields">
        <NumericField label={tr("Prediction cutoff (s)")} value={draft.asOf} min={time.start} max={time.end} placeholder={String(time.end)} onChange={value => set("asOf", value)} />
        <NumericField label={tr("Forecast horizon (s)")} value={draft.horizonSeconds} required min={.02} max={3600} onChange={value => set("horizonSeconds", value)} />
        <NumericField label={tr("Forecast step (s)")} value={draft.stepSeconds} required min={.02} max={10} onChange={value => set("stepSeconds", value)} />
        <NumericField label={tr("Maximum measurement age (s)")} value={draft.maxObservationAgeSeconds} min={0} max={300} onChange={value => set("maxObservationAgeSeconds", value)} />
        <label>{tr("Future input assumption")}<select value={draft.mode} onChange={event => onChange({ ...draft, mode: event.target.value as ForecastDraft["mode"] })}>
          <option value="hold">{tr("Hold observed commands")}</option><option value="override">{tr("Set fixed future commands")}</option>
        </select></label>
        {draft.mode === "override" && <>
          <NumericField label={tr("Future pump command (%)")} value={draft.pumpCommand} min={0} max={150} required={!draft.valveOpening} onChange={value => set("pumpCommand", value)} />
          <NumericField label={tr("Future connection valve opening (fraction)")} value={draft.valveOpening} min={.01} max={1} onChange={value => set("valveOpening", value)} />
        </>}
        <NumericField label={tr("Assumed constant leak coefficient")} value={draft.leakCoefficient} min={0} max={.1} placeholder="0" onChange={value => set("leakCoefficient", value)} />
      </div>
      <p className="ws-muted">{tr("The forecast uses measured inputs through the cutoff. A blank cutoff uses the dataset end. Fixed commands are scenario assumptions.")}</p>
      <details className="safety-policy"><summary>{tr("Override nominal model parameters")}</summary>
        <div className="ws-form-grid safety-fields">{forecastParameters.map(key => {
          const [label, unit, min, max] = nominalFields[key];
          const configured = dataset.metadata.model?.config?.[key];
          return <NumericField key={key} label={`${tr(label)} (${tr(unit)})`} value={draft.parameters[key] || ""} min={min} max={max}
            placeholder={typeof configured === "number" ? String(configured) : undefined} onChange={value => onChange({ ...draft, parameters: { ...draft.parameters, [key]: value } })} />;
        })}</div>
      </details>
      <div className="ws-form-grid safety-fields">
        <NumericField label={tr("Uncertainty samples")} value={draft.samples} integer min={0} max={128} onChange={value => set("samples", value)} />
        {Number(draft.samples) > 0 && <NumericField label={tr("Scenario seed")} value={draft.seed} required integer min={0} max={2147483647} onChange={value => set("seed", value)} />}
      </div>
      <details className="safety-policy" open={Number(draft.samples) > 0 || undefined}><summary>{tr("Uncertainty ranges")}</summary>
        <fieldset className="safety-ranges" aria-label={tr("Uncertainty ranges")}>
        <p className="ws-muted">{tr("Use lower and upper deviations from nominal. Fractional deviations are relative for hydraulic coefficients and nominal pump flow. Pump command deviations are percentage points.")}</p>
        {uncertaintyParameters.map(key => {
          const [label, unit] = uncertaintyLabels[key];
          const [min, max] = uncertaintyBounds[key];
          const range = draft.ranges[key];
          function setRange(next?: [string, string]) {
            const ranges = { ...draft.ranges };
            if (next) ranges[key] = next; else delete ranges[key];
            onChange({ ...draft, ranges });
          }
          return <div className="safety-range" key={key}>
            <label className="ws-inline safety-check"><input type="checkbox" checked={Boolean(range)} onChange={event => setRange(event.target.checked ? ["0", "0"] : undefined)} />{tr(label)} ({tr(unit)})</label>
            {range && <>
              <NumericField label={tr("Lower deviation")} value={range[0]} min={min} max={range[1] ? Number(range[1]) : max} required onChange={value => setRange([value, range[1]])} />
              <NumericField label={tr("Upper deviation")} value={range[1]} min={range[0] ? Number(range[0]) : min} max={max} required onChange={value => setRange([range[0], value])} />
            </>}
          </div>;
        })}
        </fieldset>
      </details>
    </>}
  </fieldset>;
}
