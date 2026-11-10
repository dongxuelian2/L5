import { useEffect, useRef, useState } from "react";
import { t as tr, useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { api, go, message } from "./api";
import { Plot } from "./Charts";
import { dateLabel, number, type Dataset, type TimeAxis } from "./types";
import type { Scenario } from "./modelTypes";
import type { EstimationProps, EstimationRun, EstimationScore, EstimationSummary, Observability } from "./estimationTypes";
import "./estimation.css";

const states = ["level1", "level2"];
const nominalModel = {area1:1, area2:1, connection:.04, outlet:.03, pumpRate:.03, pumpControl:100, valve:1, outletValve:1, tankHeight:2.5};
const sensorNames = (s:string[]) => s.length ? s.map(k => tr(k === "level1" ? "Tank 1" : "Tank 2")).join(" + ") : tr("No level sensors");
const fmt = (v:number|null|undefined) => v == null ? "—" : number(v);

function ObservabilityTable({values}:{values:Observability[]}) {
  return <section className="ws-panel estimation-observability"><h2>{tr("Local observability")}</h2>
    <p>{tr("O = [H; HA] uses the continuous hydraulic Jacobian at the selected point. Rank is local and does not establish global nonlinear observability. Singular values mix measurement and derivative scales in SI units; conditioning is a diagnostic, not an information bound.")}</p>
    <div className="ws-table-scroll"><table><thead><tr>{["Sensors", "Rank", "Singular values", "Condition number", "Interpretation"].map(k=><th key={k}>{tr(k)}</th>)}</tr></thead><tbody>{values.map(v=><tr key={v.sensors.join() || "none"}><td>{sensorNames(v.sensors)}</td><td>{v.rank == null ? "—" : `${v.rank}/2`}</td><td>{v.singularValues.map(fmt).join(" · ") || "—"}</td><td>{fmt(v.condition)}</td><td>{tr(v.status === "nondifferentiable" ? "Nondifferentiable flow" : v.poorlyObservable ? "Poorly observable" : "Locally observable")}</td></tr>)}</tbody></table></div>
    <p className="ws-muted">{tr("One sensor can reconstruct both states when hydraulic coupling is nonzero at a smooth point. With a fully closed connection valve, the unmeasured tank is unobservable. Equal levels and dry outlets have no classical square-root Jacobian.")}</p>
    <details><summary>{tr("Linearization matrices and operating point")}</summary><pre>{JSON.stringify(values,null,2)}</pre></details>
  </section>;
}

function Accuracy({score}:{score:EstimationScore|null}) {
  if (!score) return <p className="ws-muted">{tr("No hidden state is available for this Dataset. Accuracy, coverage and NEES cannot be calculated.")}</p>;
  return <><div className="ws-table-scroll"><table><thead><tr><th>{tr("Method")}</th><th>{tr("State")}</th><th>RMSE (m)</th><th>MAE (m)</th><th>{tr("Scored samples")}</th></tr></thead><tbody>{["estimate","openLoop","direct"].flatMap(method=>score.methods[method].map((v,j)=><tr key={`${method}${j}`}><td>{tr(method === "estimate" ? "Extended Kalman filter" : method === "openLoop" ? "Open-loop model" : "Current measurement")}</td><td>{sensorNames([states[j]])}</td><td>{fmt(v.rmse)}</td><td>{fmt(v.mae)}</td><td>{v.count}</td></tr>))}</tbody></table></div>
    <p>{tr("Empirical 95% coverage")}: {score.coverage95.map(v=>`${fmt(100*v)}%`).join(" · ")} · {tr("Mean NEES (2 states)")}: {fmt(score.meanNEES)} ({score.neesCount}) · {tr("Converged through run end")}: {fmt(score.convergenceTime)} s ({score.convergenceTolerance} m)</p>
    {score.worseThanOpenLoop.some(Boolean) && <p className="ws-notice">{tr("EKF is worse than the open-loop baseline on at least one state in this run.")}</p>}
  </>;
}

export function EstimationResults({run,onExport,busy}:{run:EstimationRun;onExport:()=>void;busy:boolean}) {
  useLocale();
  const all = run.result.rows;
  const [range,setRange] = useState<[number,number]>([all[0].t,all[all.length-1].t]);
  const [at,setAt] = useState(all[0].t);
  const rows = all.filter(r=>r.t>=range[0] && r.t<=range[1]);
  const times = rows.map(r=>r.t);
  const axis:TimeAxis = {kind:"numeric",column:"t",origin:null,start:all[0].t,end:all[all.length-1].t};
  const sample = rows.find(r=>r.t>=at) || rows[rows.length-1];
  const select = {selectedTime:at,onSelectTime:setAt,onHoverTime:setAt,timeDomain:range};
  return <section className="estimation-results"><div className="ws-panel"><div className="ws-inline ws-between"><div><div className="ws-kicker">{tr("SAVED ESTIMATION")}</div><h2>{run.name}</h2><p>{dateLabel(run.createdAt)} · {sensorNames(run.result.sensors)} · {run.result.predictionOnly} {tr("prediction-only rows")}</p></div><button className="ws-primary" disabled={busy} onClick={onExport}>{tr("Export estimates as Dataset")}</button></div>
      <p>{tr("Green: EKF · blue: observations · amber: open-loop · gray: prior prediction · purple: conditional 95% interval. Gaps remain missing.")}</p>
      <p className="ws-muted">{tr("Intervals condition on the assumed model, Q and R. Bias, unmodeled faults, boundary projection and nonlinearities can invalidate Gaussian calibration. NIS has the current measurement dimension (1 or 2); NEES has 2 states. Chi-square expectations assume a correct model and unbiased independent Gaussian disturbances. Time samples are correlated; these are diagnostics, not independent confidence tests.")}</p>
      {run.result.warnings.map(w=><p className="ws-notice" key={w}>{tr(w === "nonsmooth-flow" ? "Near a dry or equal-level boundary, the filter uses a finite-resolution secant. Local Gaussian uncertainty may be unreliable." : "A negative posterior height was projected to zero. Its covariance is an untruncated Gaussian approximation.")}</p>)}
      <div className="ws-form-grid"><label>{tr("Window start (s)")}<input type="number" value={range[0]} min={axis.start} max={range[1]} onChange={e=>{const v=Number(e.target.value);if(v>=axis.start && v<=range[1])setRange([v,range[1]]);}} /></label><label>{tr("Window end (s)")}<input type="number" value={range[1]} min={range[0]} max={axis.end} onChange={e=>{const v=Number(e.target.value);if(v>=range[0] && v<=axis.end)setRange([range[0],v]);}} /></label></div>
      {sample && <div className="ws-table-scroll"><table><caption>{tr("Shared cursor")}: {fmt(sample.t)} s</caption><thead><tr>{["State","Measured or inferred","Observation","Estimate","Prior prediction","Standard deviation"].map(k=><th key={k}>{tr(k)}</th>)}</tr></thead><tbody>{states.map((k,j)=><tr key={k}><td>{sensorNames([k])}</td><td>{tr(sample.observed[j] == null ? "Inferred at this time" : "Directly measured at this time")}</td><td>{fmt(sample.observed[j])}</td><td>{fmt(sample.estimate[j])}</td><td>{fmt(sample.prediction[j])}</td><td>{fmt(Math.sqrt(sample.covariance[j][j]))}</td></tr>)}</tbody></table></div>}
    </div>
    {states.map((key,j)=><div key={key}><Plot times={times} values={rows.map(r=>r.estimate[j])} title={`${sensorNames([key])} · ${tr("state estimate")} (m)`} axis={axis} {...select} bands={[{lower:rows.map(r=>r.lower[j]),upper:rows.map(r=>r.upper[j]),color:"#c5a6ef",title:tr("Conditional 95% interval")}]} overlays={[
      {times,values:rows.map(r=>r.observed[j]),title:tr("Observation"),color:"#8cbfe8",points:true},
      {times,values:rows.map(r=>r.openLoop[j]),title:tr("Open-loop model"),color:"#e2bc75"},
      {times,values:rows.map(r=>r.prediction[j]),title:tr("Prior prediction"),color:"#a0a99b"}]} />
      <Plot times={times} values={rows.map(r=>r.innovation[j])} title={`${sensorNames([key])} · ${tr("Innovation and posterior residual")} (m)`} axis={axis} {...select} overlays={[
        {times,values:rows.map(r=>r.residual[j]),title:tr("Posterior residual"),color:"#8cbfe8"},
        ...[-1,1].map(sign=>({times,values:rows.map(r=>r.innovationSd[j] == null ? null : sign*1.96*r.innovationSd[j]!),title:`${sign} · ${tr("Innovation 95% bound")}`,color:"#c5a6ef"}))]} /></div>)}
    <Plot times={times} values={rows.map(r=>r.covariance[0][0])} title={tr("Posterior covariance (m²)")} axis={axis} {...select} overlays={[{times,values:rows.map(r=>r.covariance[1][1]),title:"P22",color:"#8cbfe8"},{times,values:rows.map(r=>r.covariance[0][1]),title:"P12",color:"#e2bc75"}]} />
    <Plot times={times} values={rows.map(r=>r.nis)} title={tr("Normalized innovation squared (NIS)")} axis={axis} {...select} overlays={[{times,values:rows.map(r=>r.dof === 1 ? 3.841459 : r.dof === 2 ? 5.991465 : null),title:tr("Pointwise chi-square 95% bound"),color:"#e2bc75"}]} />
    <section className="ws-panel"><h2>{tr("Retrospective evaluation")}</h2><Accuracy score={run.score} />
      <h3>{tr("Innovation consistency")}</h3><p>{tr("Mean innovations (m)")}: {run.result.innovationMean.map(fmt).join(" · ")}</p>
      <div className="ws-table-scroll"><table><thead><tr><th>{tr("Dimension")}</th><th>{tr("Updates")}</th><th>{tr("Mean NIS / expected")}</th><th>{tr("Within 95% bound")}</th></tr></thead><tbody>{Object.entries(run.result.innovationConsistency).map(([d,v])=><tr key={d}><td>{d}</td><td>{v.count}</td><td>{fmt(v.meanNIS)} / {v.expectedMean}</td><td>{fmt(v.fraction95*100)}%</td></tr>)}</tbody></table></div>
      <h3>{tr("Sensor configuration comparison")}</h3><p>{tr("All configurations use the same frozen observations and filter settings. Direct measurement errors are scored only where a real observation exists.")}</p>
      <div className="ws-table-scroll"><table><thead><tr><th>{tr("Sensors")}</th><th>RMSE 1 / 2 (m)</th><th>{tr("95% coverage 1 / 2")}</th><th>{tr("Prediction-only rows")}</th></tr></thead><tbody>{run.comparisons.map(c=><tr key={c.sensors.join() || "none"}><td>{sensorNames(c.sensors)}</td><td>{c.score?.methods.estimate.map(v=>fmt(v.rmse)).join(" / ") || "—"}</td><td>{c.score?.coverage95.map(v=>`${fmt(100*v)}%`).join(" / ") || "—"}</td><td>{c.predictionOnly}</td></tr>)}</tbody></table></div>
    </section>
    <ObservabilityTable values={run.observability} />
    <details className="ws-panel"><summary>{tr("Frozen inputs, settings and provenance")}</summary><p>SHA-256: {run.inputSha256}</p>{run.source.datasetId && <a className="ws-link" href={`#/workspaces/${run.workspaceId}/datasets/${run.source.datasetId}`}>{run.source.datasetName}</a>}<pre>{JSON.stringify({request:run.request,source:run.source,inputs:run.inputs},null,2)}</pre></details>
  </section>;
}

export function EstimationWorkspace({workspaceId,datasets,runId,onSaved}:EstimationProps) {
  useLocale();
  const [runs,setRuns] = useState<EstimationSummary[]>([]), [scenarios,setScenarios] = useState<Scenario[]>([]);
  const [run,setRun] = useState<EstimationRun|null>(null), [error,setError] = useState(""), [busy,setBusy] = useState(false), [loading,setLoading] = useState(true);
  const [source,setSource] = useState("simulation"), [datasetId,setDatasetId] = useState(datasets[0]?.id || ""), [scenarioId,setScenarioId] = useState("");
  const [scenarioVersion,setScenarioVersion] = useState<number|undefined>(), [jacobianStep,setJacobianStep] = useState(1e-5);
  const [simulationBase,setSimulationBase] = useState<Record<string,unknown>>({});
  const [name,setName] = useState(""), [fault,setFault] = useState("healthy"), [duration,setDuration] = useState(180), [seed,setSeed] = useState(31);
  const [noise,setNoise] = useState([.02,.02]), [every,setEvery] = useState([1,3]), [dropout,setDropout] = useState(.1), [irregular,setIrregular] = useState(true);
  const [sensors,setSensors] = useState(states), [known,setKnown] = useState(["pumpControl","valve"]), [compare,setCompare] = useState(true);
  const [mapping,setMapping] = useState<Record<string,string>>({level1:"",level2:"",pumpControl:"",valve:""});
  const [initial,setInitial] = useState([1.2,.7]), [initialTime,setInitialTime] = useState(0), [maxStep,setMaxStep] = useState(.1);
  const [p,setP] = useState("[[0.16,0],[0,0.16]]"), [q,setQ] = useState("[[0.000001,0],[0,0.000001]]"), [r,setR] = useState("[[0.0004,0],[0,0.0004]]");
  const [model,setModel] = useState(JSON.stringify(nominalModel,null,2)), [point,setPoint] = useState([1.5625,1]), [obs,setObs] = useState<Observability[]>([]);
  const [exported,setExported] = useState<Dataset|null>(null);
  const operation = useRef<AbortController|null>(null);
  const selected = datasets.find(d=>d.id===datasetId);
  function restore(value:EstimationRun) {
    const s=value.source,c=value.result.config;
    setName(value.name);setSource(s.kind);setDatasetId(s.datasetId || "");setScenarioId(s.scenarioId || "");
    setScenarioVersion(s.scenarioSnapshot?.version ?? s.version);
    setSimulationBase(s.kind === "simulation" ? {...s.simulation} : {});
    setFault(s.simulation?.fault || "healthy");setDuration(s.simulation?.duration ?? 180);setSeed(s.simulation?.seed ?? 31);
    setNoise(s.noise || [.02,.02]);setEvery(s.every || [1,3]);setDropout(s.dropout ?? .1);setIrregular(s.irregular ?? false);
    setMapping(Object.fromEntries(["level1","level2","pumpControl","valve"].map(k=>[k,s.mapping?.[k] || ""])));
    setSensors(value.result.sensors);setKnown(value.request.knownControls || ["pumpControl","valve"]);setCompare(value.request.compareSensors ?? false);
    setInitial(c.initialState);setInitialTime(c.initialTime);setMaxStep(c.maxStep);setJacobianStep(c.jacobianStep);
    setP(JSON.stringify(c.initialCovariance));setQ(JSON.stringify(c.processCovariance));setR(JSON.stringify(c.measurementCovariance));
    setModel(JSON.stringify(value.request.model || value.result.model,null,2));setPoint(value.request.operatingPoint || [1.5625,1]);
  }
  useEffect(()=>{
    const c = new AbortController();setLoading(true);
    Promise.all([api<{runs:EstimationSummary[]}>(`/workspaces/${workspaceId}/estimations`,undefined,"GET",c.signal),api<{scenarios:Scenario[]}>(`/workspaces/${workspaceId}/scenarios`,undefined,"GET",c.signal)])
      .then(([a,b])=>{if(!c.signal.aborted){setRuns(a.runs);setScenarios(b.scenarios.filter(s=>s.modelId==="coupled-tanks"));}})
      .catch(e=>{if(!c.signal.aborted)setError(message(e));}).finally(()=>{if(!c.signal.aborted)setLoading(false);});
    return ()=>{c.abort();operation.current?.abort();};
  },[workspaceId]);
  useEffect(()=>{
    operation.current?.abort();setBusy(false);setRun(null);setExported(null);setError("");
    if(!runId)return;
    const c = new AbortController();operation.current=c;setBusy(true);
    api<EstimationRun>(`/estimations/${runId}`,undefined,"GET",c.signal).then(value=>{if(!c.signal.aborted){if(value.workspaceId!==workspaceId)throw new Error("Estimation belongs to another Workspace.");setRun(value);restore(value);}})
      .catch(e=>{if(!c.signal.aborted)setError(message(e));}).finally(()=>{if(!c.signal.aborted)setBusy(false);});
    return ()=>c.abort();
  },[runId,workspaceId]);
  function toggle(values:string[],key:string,set:(next:string[])=>void) {set(values.includes(key) ? values.filter(s=>s!==key) : [...values,key]);}
  async function action(kind:"run"|"observability"|"export") {
    operation.current?.abort();const c = new AbortController();operation.current=c;setBusy(true);setError("");
    try {
      if(kind==="export" && run) {
        const d=await api<Dataset>(`/estimations/${run.id}/dataset`,{},"POST",c.signal);
        if(!c.signal.aborted){setExported(d);onSaved(d);}return;
      }
      const physical = JSON.parse(model);
      if(kind==="observability") {
        const values=await Promise.all([states,["level1"],["level2"],[]].map(s=>api<Observability>(`/workspaces/${workspaceId}/estimations/observability`,{model:physical,point,sensors:s},"POST",c.signal)));
        if(!c.signal.aborted)setObs(values);return;
      }
      const acquisition = {noise,every,dropout,irregular};
      const input = source === "dataset" ? {kind:source,datasetId,mapping:Object.fromEntries(Object.entries(mapping).map(([k,v])=>[k,v || null]))} : source === "scenario" ? {kind:source,scenarioId,version:scenarioVersion,...acquisition} : {kind:source,simulation:{...simulationBase,fault,duration,step:simulationBase.step ?? .5,start:Math.min(Number(simulationBase.start ?? 40),duration),seed},...acquisition};
      const next = await api<EstimationRun>(`/workspaces/${workspaceId}/estimations`,{name:name || tr("Tank state estimation"),source:input,model:physical,sensors,knownControls:known,compareSensors:compare,operatingPoint:point,
        config:{initialState:initial,initialTime,maxStep,jacobianStep,initialCovariance:JSON.parse(p),processCovariance:JSON.parse(q),measurementCovariance:JSON.parse(r)}},"POST",c.signal);
      if(!c.signal.aborted){setRun(next);setRuns(v=>[{id:next.id,name:next.name,created_at:next.createdAt},...v]);setExported(null);go(`workspaces/${workspaceId}/estimations/${next.id}`);}
    }catch(e){if(!c.signal.aborted)setError(e instanceof SyntaxError ? "Enter valid JSON for the model and covariance matrices." : message(e));}finally{if(!c.signal.aborted)setBusy(false);}
  }
  return <div className="estimation-workspace"><div className="ws-page-title"><div><div className="ws-kicker">{tr("12 / STATE ESTIMATION")}</div><h1>{tr("State estimation & sensor fusion")}</h1><p>{tr("Reconstruct coupled-tank levels from incomplete, asynchronous observations with a causal nonlinear EKF.")}</p></div></div>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}{(busy || loading) && <p role="status">{tr("Computing or opening estimation…")}</p>}
    <section className="ws-panel"><label>{tr("Saved estimations")}<select value={runId || ""} disabled={busy} onChange={e=>go(`workspaces/${workspaceId}/estimations${e.target.value ? `/${e.target.value}` : ""}`)}><option value="">{tr("New estimation")}</option>{runs.map(v=><option value={v.id} key={v.id}>{v.name} · {dateLabel(v.created_at)} · {v.id.slice(0,6)}</option>)}</select></label></section>
    <details className="ws-panel" open={!run}><summary>{tr("Configure estimation experiment")}</summary>
      <form onSubmit={e=>{e.preventDefault();void action("run");}}><fieldset disabled={busy || loading}><div className="ws-form-grid">
        <label>{tr("Run name")}<input value={name} maxLength={160} placeholder={tr("Tank state estimation")} onChange={e=>setName(e.target.value)} /></label>
        <label>{tr("Observation source")}<select value={source} onChange={e=>setSource(e.target.value)}><option value="simulation">{tr("Reproducible simulation")}</option><option value="scenario">{tr("Saved tank scenario")}</option><option value="dataset">{tr("Dataset with level measurements")}</option></select></label>
        {source === "dataset" ? <label>{tr("Dataset")}<select value={datasetId} onChange={e=>{setDatasetId(e.target.value);setMapping({level1:"",level2:"",pumpControl:"",valve:""});setInitialTime(datasets.find(d=>d.id===e.target.value)?.metadata.time.start || 0);}}><option value="">{tr("Choose a Dataset")}</option>{datasets.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></label> : source === "scenario" ? <label>{tr("Saved tank scenario")}<select value={scenarioId} onChange={e=>{setScenarioId(e.target.value);setScenarioVersion(scenarios.find(s=>s.id===e.target.value)?.version);}}><option value="">{tr("Choose a scenario")}</option>{scenarios.map(s=><option key={s.id} value={s.id}>{s.name} · v{s.id===scenarioId && scenarioVersion ? scenarioVersion : s.version}</option>)}</select></label> : <>
          <label>{tr("Simulated fault")}<select value={fault} onChange={e=>setFault(e.target.value)}>{["healthy","pump_degradation","valve_restriction","tank_leak","sensor_bias"].map(k=><option key={k} value={k}>{tr({healthy:"Healthy operation",pump_degradation:"Inlet pump degradation",valve_restriction:"Connection valve restriction",tank_leak:"Tank 1 leak",sensor_bias:"Tank 2 level sensor bias"}[k]!)}</option>)}</select></label>
          <label>{tr("Duration (s)")}<input type="number" required min={1} max={3000} value={duration} onChange={e=>setDuration(Number(e.target.value))} /></label><label>{tr("Random seed")}<input type="number" required min={0} max={2147483647} value={seed} onChange={e=>setSeed(Number(e.target.value))} /></label>
        </>}
        {source === "dataset" && ["level1","level2","pumpControl","valve"].map(k=><label key={k}>{tr({level1:"Tank 1 measurement (m)",level2:"Tank 2 measurement (m)",pumpControl:"Known pump command (%)",valve:"Known valve command (0–1)"}[k]!)}<select value={mapping[k]} onChange={e=>setMapping(v=>({...v,[k]:e.target.value}))}><option value="">{tr("Unavailable / use nominal control")}</option>{selected?.metadata.columns.map(col=><option key={col.name}>{col.name}</option>)}</select></label>)}
        {source !== "dataset" && <>{states.map((k,j)=><label key={`${k}noise`}>{sensorNames([k])} · {tr("noise SD (m)")}<input type="number" required min={0} max={1} step="any" value={noise[j]} onChange={e=>setNoise(noise.map((v,i)=>i===j ? Number(e.target.value) : v))} /></label>)}{states.map((k,j)=><label key={`${k}rate`}>{sensorNames([k])} · {tr("sample every N base ticks")}<input type="number" required min={1} max={100} value={every[j]} onChange={e=>setEvery(every.map((v,i)=>i===j ? Number(e.target.value) : v))} /></label>)}<label>{tr("Sensor dropout probability")}<input type="number" required min={0} max={1} step="any" value={dropout} onChange={e=>setDropout(Number(e.target.value))} /></label><label className="estimation-check"><input type="checkbox" checked={irregular} onChange={e=>setIrregular(e.target.checked)} />{tr("Irregular observation timestamps")}</label></>}
      </div>
      <p className="ws-muted">{tr("Measurements must be in meters; timestamps in dataset seconds. Pump commands use percent, valves use fractions. Only original observations are assimilated; derived or interpolated samples are excluded. Unknown controls use the explicit nominal model.")}</p>
      <div className="ws-inline">{states.map(k=><label className="estimation-check" key={k}><input type="checkbox" checked={sensors.includes(k)} onChange={()=>toggle(sensors,k,setSensors)} />{tr("Observe")} {sensorNames([k])}</label>)}{["pumpControl","valve"].map(k=><label className="estimation-check" key={k}><input type="checkbox" checked={known.includes(k)} onChange={()=>toggle(known,k,setKnown)} />{tr(k==="pumpControl" ? "Use known pump commands" : "Use known valve commands")}</label>)}<label className="estimation-check"><input type="checkbox" checked={compare} onChange={e=>setCompare(e.target.checked)} />{tr("Compare both / single / no sensors")}</label></div>
      <div className="ws-form-grid">{states.map((k,j)=><label key={k}>{sensorNames([k])} · {tr("initial estimate (m)")}<input type="number" required min={0} max={100} step="any" value={initial[j]} onChange={e=>setInitial(initial.map((v,i)=>i===j ? Number(e.target.value) : v))} /></label>)}<label>{tr("Initial time (s)")}<input type="number" required min={0} step="any" value={initialTime} onChange={e=>setInitialTime(Number(e.target.value))} /></label><label>{tr("Maximum integration step (s)")}<input type="number" required min={.005} max={.25} step="any" value={maxStep} onChange={e=>setMaxStep(Number(e.target.value))} /></label></div>
      <div className="ws-form-grid">{[["P0 · initial covariance (m²)",p,setP],["Q · process spectral density (m²/s)",q,setQ],["R · measurement covariance (m²)",r,setR]].map(([label,value,set])=><label key={String(label)}>{tr(String(label))}<textarea value={String(value)} rows={3} onChange={e=>(set as (v:string)=>void)(e.target.value)} /></label>)}</div>
      <details><summary>{tr("Assumed physical model and operating point")}</summary><p>{tr("Edit physical parameters to study mismatch. These assumptions are independent of the simulator fault and hidden initial state. A zero valve opening represents disconnected tanks.")}</p><textarea aria-label={tr("Assumed physical model")} className="estimation-model" rows={12} value={model} onChange={e=>setModel(e.target.value)} /><div className="ws-form-grid">{states.map((k,j)=><label key={k}>{sensorNames([k])} · {tr("operating point (m)")}<input type="number" required min={0} max={100} step="any" value={point[j]} onChange={e=>setPoint(point.map((v,i)=>i===j ? Number(e.target.value) : v))} /></label>)}</div><label>{tr("Jacobian difference step (m)")}<input type="number" required min={1e-7} max={1e-3} step="any" value={jacobianStep} onChange={e=>setJacobianStep(Number(e.target.value))} /></label><button type="button" onClick={()=>void action("observability")}>{tr("Analyze local observability")}</button></details>
      <div className="ws-inline"><button className="ws-primary" type="submit">{tr("Run estimation and save")}</button></div></fieldset></form>
    </details>
    {obs.length > 0 && <ObservabilityTable values={obs} />}
    {exported && <p className="ws-notice">{tr("Estimates saved as Dataset")}: <a className="ws-link" href={`#/workspaces/${workspaceId}/datasets/${exported.id}`}>{exported.name} ↗</a></p>}
    {run && <EstimationResults key={run.id} run={run} busy={busy} onExport={()=>void action("export")} />}
  </div>;
}
