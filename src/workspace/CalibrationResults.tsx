import { useState } from "react";
import { t as tr, useLocale } from "../i18n";
import { Plot } from "./Charts";
import { number } from "./types";
import type { CalibrationEvaluation, CalibrationRun, ResidualMetric } from "./calibrationTypes";

const parameterLabel = (key: string) => tr(({pumpRate:"Nominal pump flow",connection:"Connection discharge coefficient",outlet:"Outlet discharge coefficient",initial1:"Initial Tank 1 level",initial2:"Initial Tank 2 level",pumpEfficiency:"Pump efficiency factor"} as Record<string,string>)[key] || key);

export function MetricTable({ metrics, original }: { metrics: Record<string, ResidualMetric>; original: Record<string, ResidualMetric> }) {
  return <div className="ws-table-scroll"><table><thead><tr>{["Observed output", "Original RMSE", "Calibrated RMSE", "MAE", "Residual bias", "Lag-1 correlation"].map(k => <th key={k}>{tr(k)}</th>)}</tr></thead><tbody>{Object.entries(metrics).map(([key,m]) => <tr key={key}><th>{tr(key)}</th><td>{number(original[key].rmse)}</td><td className="ws-accent">{number(m.rmse)}</td><td>{number(m.mae)}</td><td>{number(m.bias)}</td><td>{number(m.lag1)}{m.systematic && <span className="twin-flag">{tr("Systematic residual")}</span>}</td></tr>)}</tbody></table></div>;
}

function Evaluation({ evaluation, validation }: { evaluation: CalibrationEvaluation; validation: boolean }) {
  const [signal,setSignal]=useState(Object.keys(evaluation.observed)[0]);
  const key=signal in evaluation.observed ? signal : Object.keys(evaluation.observed)[0];
  const times=evaluation.times;
  const axis={kind:"numeric" as const,column:"t",origin:null,start:times[0],end:times[times.length-1]};
  const m=evaluation.metrics[key], envelope=evaluation.parameterEnvelope?.[key];
  const maxCount=Math.max(...m.histogram.counts,1);
  return <section className="ws-panel twin-evaluation"><div className="ws-section-heading"><h2>{tr(validation ? "Independent validation" : "Calibration fit")}</h2><label>{tr("Observed output")}<select aria-label={tr(validation ? "Validation output" : "Calibration output")} value={key} onChange={e=>setSignal(e.target.value)}>{Object.keys(evaluation.observed).map(s=><option key={s} value={s}>{tr(s)}</option>)}</select></label></div>
    <p className="ws-muted">{evaluation.reference.datasetName} · {evaluation.reference.range.join(" – ")} s · {tr(validation ? "Fresh measured initial state; first observation excluded from metrics." : "Free trajectory fitted only to calibration observations.")}</p>
    <div className="twin-legend"><span style={{color:"#8cbfe8"}}>● {tr("Observed")}</span><span style={{color:"#b5ed9a"}}>● {tr("Calibrated")}</span><span style={{color:"#e2bc75"}}>● {tr("Original")}</span>{envelope && <span style={{color:"#c1a4ef"}}>● {tr("Local parameter envelope (±1.96σ)")}</span>}</div>
    <Plot times={times} values={evaluation.observed[key]} title={tr(key)} axis={axis} color="#8cbfe8" overlays={[
      {times,values:evaluation.predicted[key],title:tr("Calibrated"),color:"#b5ed9a"},
      {times,values:evaluation.original[key],title:tr("Original"),color:"#e2bc75"},
      ...(envelope ? [{times,values:envelope.lower,title:tr("Local lower envelope"),color:"#c1a4ef"},{times,values:envelope.upper,title:tr("Local upper envelope"),color:"#c1a4ef"}] : [])]} />
    <MetricTable metrics={evaluation.metrics} original={evaluation.originalMetrics} />
    <details open><summary>{tr("Residual diagnostics")}</summary><Plot times={times} values={evaluation.residuals[key]} title={tr("Prediction minus observation")} axis={axis} color="#e9927d" threshold={0} thresholdLabel={tr("Zero residual")} />
      <div className="twin-residual-summary"><div><h3>{tr("Residual distribution")}</h3><svg viewBox="0 0 420 115" role="img" aria-label={tr("Residual histogram")}>{m.histogram.counts.map((count,i)=><rect key={i} x={i*34+5} y={90-count/maxCount*80} width="28" height={count/maxCount*80} fill="#e9927d"><title>{number(m.histogram.edges[i])} – {number(m.histogram.edges[i+1])}: {count}</title></rect>)}<text x="5" y="110">{number(m.histogram.edges[0])}</text><text x="413" y="110" textAnchor="end">{number(m.histogram.edges[m.histogram.edges.length-1])}</text></svg></div><dl><dt>{tr("5 / 50 / 95 percentiles")}</dt><dd>{m.quantiles.map(v=>number(v)).join(" / ")}</dd><dt>{tr("Residual standard deviation")}</dt><dd>{number(m.std)}</dd><dt>{tr("Step-halving RMSE difference")}</dt><dd>{number(evaluation.numericalStepDifferenceRmse[key])}</dd><dt>{tr("Mass conservation error (m³)")}</dt><dd>{evaluation.massBalanceError.toExponential(2)}</dd></dl></div>
      <p className="ws-muted">{tr("Residual bias and serial correlation can indicate model mismatch, input errors or a wrong noise model; they are diagnostics, not fault labels.")}</p></details>
    {!!evaluation.multiStep?.length && <details><summary>{tr("Rolling multi-step prediction")}</summary><p className="ws-muted">{tr("Each origin uses only its measured initial levels and subsequent actuator commands. Parameters stay frozen. Horizons use the first sample at or after the requested time; origins may overlap.")}</p>{evaluation.multiStep.map(row=><div key={row.horizonSeconds}><h3>{row.horizonSeconds} s · {row.origins} {tr("origins")}</h3><MetricTable metrics={row.metrics} original={row.originalMetrics} /></div>)}</details>}
  </section>;
}

export function CalibrationResults({ run }: { run: CalibrationRun }) {
  useLocale();
  const result=run.result;
  if (!result) return null;
  const id=result.identifiability, names=Object.keys(result.parameters);
  return <div className="twin-results"><section className="ws-panel"><div className="ws-section-heading"><h2>{tr("Numerical identification")}</h2><span className="ws-badge">{tr(result.optimizer.converged ? "Converged" : "Optimizer incomplete")}</span></div>
    <div className="ws-stats"><div><strong>{id.rank} / {id.parameterCount}</strong><span>{tr("Local sensitivity rank")}</span></div><div><strong>{result.optimizer.evaluations}</strong><span>{tr("Optimizer evaluations")}</span></div><div><strong>{number(result.reducedChiSquare)}</strong><span>{tr("Reduced χ²")}</span></div><div><strong>{number(result.durationMs/1000)} s</strong><span>{tr("Elapsed time")}</span></div></div>
    {result.warnings.map(w=><p className="ws-notice" key={w}>{tr(`twin.warning.${w}`)}</p>)}
    <div className="ws-table-scroll"><table><thead><tr>{["Physical parameter","Initial guess","Fitted value","Bounds","Local standard error"].map(k=><th key={k}>{tr(k)}</th>)}</tr></thead><tbody>{Object.entries(result.parameters).map(([key,p])=><tr key={key}><th>{parameterLabel(key)}<small> {p.unit}</small></th><td>{number(p.initial)}</td><td>{number(p.value)}</td><td>{number(p.lower)} – {number(p.upper)}</td><td>{result.uncertainty.standardErrors?.[key] != null ? number(result.uncertainty.standardErrors[key]) : tr("Withheld")}</td></tr>)}</tbody></table></div>
    <details><summary>{tr("Convergence trace")}</summary><ol>{result.optimizer.trace.map((v,i)=><li key={i}>{v.evaluations} · {tr("Weighted cost")} {number(v.cost)}</li>)}</ol><p>{tr("First-order optimality")}: {number(result.optimizer.optimality)} · {result.optimizer.simulationCalls} {tr("objective simulations")}</p></details>
  </section>
    <section className="ws-panel"><div className="ws-section-heading"><h2>{tr("Parameter identifiability")}</h2><span className="ws-badge">{tr(`twin.status.${id.status}`)}</span></div><p>{tr("Sensitivity uses output noise weights and fixed engineering parameter scales. Numerical rank is local and does not prove global uniqueness.")}</p>
      <div className="twin-singulars">{id.singularValues.map((s,i)=><div key={i}><span>σ{i+1}</span><meter min={0} max={Math.log10(1+id.singularValues[0]) || 1} value={Math.log10(1+s)} /><code>{s.toExponential(3)}</code></div>)}</div><p className="ws-muted">{tr("Rank tolerance")}: {id.rankTolerance.toExponential(2)} · {tr("Condition number")}: {id.conditionNumber == null ? "∞" : number(id.conditionNumber)}</p>
      <div className="twin-sensitivities">{names.map(k=><div key={k}><span>{parameterLabel(k)}</span><strong>{number(id.sensitivityNorms[k])}</strong></div>)}</div>
      {!!id.weakCombinations.length && <div className="ws-notice"><h3>{tr("Poorly constrained combinations")}</h3>{id.weakCombinations.map((c,i)=><p key={i}>{Object.entries(c.combination).map(([k,v])=>`${number(v)} Δ${parameterLabel(k)}/scale`).join(" + ")} · σ={c.singularValue.toExponential(2)}</p>)}</div>}
      <details><summary>{tr(id.correlation ? "Local parameter correlation" : "Sensitivity column cosine (covariance unavailable)")}</summary><div className="ws-table-scroll"><table><thead><tr><th />{names.map(k=><th key={k}>{parameterLabel(k)}</th>)}</tr></thead><tbody>{names.map((k,i)=><tr key={k}><th>{parameterLabel(k)}</th>{names.map((other,j)=>{const value=(id.correlation || id.sensitivityCosine)[i][j];return <td key={other} style={{background:`rgba(233,146,125,${Math.abs(value)*.24})`}}>{number(value)}</td>;})}</tr>)}</tbody></table></div></details>
    </section>
    <section className="ws-panel"><h2>{tr("Uncertainty and scope")}</h2><p>{tr(result.uncertainty.available ? "Local linearized parameter uncertainty is available under the stated noise model. The envelope is an approximation, not a universal confidence guarantee." : "Parameter covariance and envelopes are withheld because local uncertainty assumptions are not supported by this fit.")}</p><div className="twin-scope">{["Measurement noise: user-specified independent Gaussian output standard deviations.","Parameter uncertainty: local sensitivity only; unestimated initial-state and input uncertainty excluded.","Model mismatch: inspect residual bias, autocorrelation and independent validation.","Numerical error: step-halving differences are reported separately; they are not statistical intervals."].map(k=><p key={k}>{tr(k)}</p>)}</div></section>
    <Evaluation key={`cal/${run.id}`} evaluation={result.calibration} validation={false} />
    {result.validation ? <Evaluation key={`val/${run.id}`} evaluation={result.validation} validation /> : <p className="ws-notice">{tr("No independent validation was selected. This fit has not been independently validated.")}</p>}
  </div>;
}
