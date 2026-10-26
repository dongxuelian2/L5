import { t as tr, useLocale } from "../i18n";
import type { Config } from "./types";

export const algorithms: Record<string,string> = { "robust-maxz":"Robust Max-Z", "pca-q":"PCA-Q", "pca-t2":"PCA-T²", ewma:"EWMA", cusum:"Page CUSUM", "window-cusum":"Finite-window CUSUM", "dpca-q":"Dynamic PCA-Q", "dpca-t2":"Dynamic PCA-T²", get "adaptive-maxz"() { return tr("Adaptive Max-Z · Experimental"); } };
const parameters: Record<string, [keyof Config, string, number, number, number, number][]> = {
  ewma:[["smoothing","EWMA smoothing λ",.25,.00001,1,.01]],
  cusum:[["reference","CUSUM reference drift k",.5,.00001,100,.05]],
  "window-cusum":[["reference","CUSUM reference drift k",.5,.00001,100,.05],["window","Lookback window (samples)",12,2,100000,1]],
  "dpca-q":[["lags","Historical lags (samples)",2,1,8,1]], "dpca-t2":[["lags","Historical lags (samples)",2,1,8,1]],
  "adaptive-maxz":[["rate","Adaptation rate",.02,.00001,.99999,.01],["guard","Update guard (z)",2.5,.00001,100,.1],["maxShift","Maximum center shift (z)",1.5,.00001,100,.1]],
};
export function algorithmParameters(algorithm: string) {
  return [...(algorithm.includes("pca") ? [["variance", tr("PCA retained variance"), .9, .5, .999999, .01] as [keyof Config, string, number, number, number, number]] : []), ...(parameters[algorithm] || [])];
}
export function AlgorithmParameters({ config, onChange }: { config: Config; onChange: (config: Config) => void }) {
  useLocale();
  return <>{algorithmParameters(config.algorithm).map(([key, label, initial, min, max]) => <label key={key}>{tr(label)}<input type="number" min={min} max={max} step={key === "lags" || key === "window" ? 1 : "any"} required value={(config[key] as number | undefined) ?? initial} onChange={e => onChange({ ...config, [key]: Number(e.target.value) })} /></label>)}</>;
}
export function AlgorithmControls({config,onChange}:{config:Config;onChange:(c:Config)=>void}) {
  useLocale();
  function set(key:keyof Config,value:unknown) { onChange({...config,[key]:value}); }
  return <>
    <div className="ws-form-grid ws-three"><label>{tr("Detection algorithm")}<select value={config.algorithm} onChange={e=>set("algorithm",e.target.value)}>{Object.entries(algorithms).map(([id,name])=><option key={id} value={id} disabled={id.startsWith("pca-") && config.signals.length<2}>{name}</option>)}</select></label>
      <label>{tr("Calibration alpha")}<input type="number" min="0.000001" max="0.499999" step="any" value={config.alpha} onChange={e=>set("alpha",Number(e.target.value))} required /></label>
      <AlgorithmParameters config={config} onChange={onChange} />
    </div>
    {config.algorithm==="adaptive-maxz" && <p className="ws-notice">{tr("Experimental: guarded adaptation can absorb a slow fault. Compare with a fixed reference detector.")}</p>}
    <label>{tr("Transformation observation policy")}<select value={config.observationPolicy || "measured"} onChange={e => set("observationPolicy", e.target.value)}><option value="measured">{tr("Original observations · processed points do not count toward coverage")}</option><option value="processed">{tr("Include processed values · interpolation and fills count toward coverage")}</option></select></label>
    <details><summary>{tr("Coverage, abstention & sensor perturbations")}</summary><div className="ws-form-grid ws-three">
      <label>{tr("Normal fit fraction")}<input type="number" min={.5} max={.9} step="any" value={config.fitFraction??.7} onChange={e=>set("fitFraction",Number(e.target.value))} /></label>
      <label>{tr("Minimum observed fraction")}<input type="number" min={.000001} max={1} step="any" value={config.minCoverage??.9} onChange={e=>set("minCoverage",Number(e.target.value))} /></label>
      <label>{tr("Alarm persistence (samples)")}<input type="number" min={1} step={1} value={config.persistence??1} onChange={e=>set("persistence",Number(e.target.value))} /></label>
    </div><fieldset><legend>{tr("Required observed signals")}</legend><div className="ws-option-grid">{config.signals.map(signal=><label key={signal}><input type="checkbox" checked={config.requiredSignals?.includes(signal)??false} onChange={e=>set("requiredSignals", e.target.checked ? [...(config.requiredSignals||[]),signal] : config.requiredSignals?.filter(s=>s!==signal))} />{signal}</label>)}</div></fieldset>
    <p className="ws-notice">{tr("Insufficient original coverage produces abstain, even after imputation. Temporal state and alarm persistence reset across abstained rows. Artificial perturbations affect the analysis window; the saved source data, normal fit and calibration remain intact.")}</p>
    <div className="ws-form-grid ws-three">{([['missingFraction',tr("Random missing fraction"),0,0,1],['noise',tr("Added noise (normal-fit std)"),0,0,100],['offset',tr("Sensor offset (normal-fit std)"),0,-100,100],['seed',tr("Perturbation seed"),1,0,2**31-1]] as const).map(([key,label,initial,min,max])=><label key={key}>{tr(label)}<input type="number" min={min} max={max} step={key==='seed'?1:'any'} value={config.stress?.[key]??initial} onChange={e=>set("stress",{...config.stress,[key]:Number(e.target.value)})} /></label>)}</div>
    <fieldset><legend>{tr("Simulate complete loss of selected sensors")}</legend><div className="ws-option-grid">{config.signals.map(signal=><label key={signal}><input type="checkbox" checked={config.stress?.missingSignals?.includes(signal)??false} onChange={e=>set("stress", {...config.stress, missingSignals:e.target.checked ? [...(config.stress?.missingSignals||[]),signal] : config.stress?.missingSignals?.filter(s=>s!==signal)})} />{signal}</label>)}</div></fieldset>
    </details>
  </>;
}
