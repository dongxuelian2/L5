import { t as tr, useLocale } from "../i18n";
import { Plot } from "./Charts";
import { number, type RuntimeRun } from "./types";
import type { ModelForecast } from "./modelTypes";

export function isModelForecast(value: unknown): value is ModelForecast {
  return Boolean(value && typeof value === "object" && "format" in value && value.format === "model-forecast-v1");
}

export function ModelForecastView({ forecast }: { forecast: ModelForecast }) {
  useLocale();
  const paths = [forecast.baseline, ...forecast.branches];
  const colors = ["#e9927d", "#b5ed9a", "#8cbadd", "#e2bc75", "#bca1de"];
  return <div className="model-forecast"><p className="ws-notice">{tr(forecast.mode)}{" "}{tr("model · observed through")}{" "}{forecast.observedThrough}{tr("s · action at")}{" "}{forecast.at}{tr("s · horizon")}{" "}{forecast.horizon}s</p>
    <div className="ws-table-scroll"><table><thead><tr><th>{tr("Branch")}</th>{forecast.metricDefinitions.map(m => <th key={m.key}>{tr(m.label)} ({tr(m.unit)})</th>)}</tr></thead><tbody>{paths.map((p,i) => <tr key={i}><th>{tr(p.action) || tr("No intervention")}</th>{forecast.metricDefinitions.map(m => <td key={m.key}>{number(p.metrics[m.key])}</td>)}</tr>)}</tbody></table></div>
    <p className="ws-muted">{paths.map((p,i) => <span key={i} style={{ color: colors[i] }}>{i ? " · " : ""}{tr(p.action) || tr("Baseline")}</span>)}</p>
    {forecast.signalDefinitions.map(s => <Plot key={s.key} title={`${tr(s.label || s.tag)} (${s.unit})`} times={paths[0].times} values={paths[0].values[s.key]} color={colors[0]} selectedTime={forecast.at} axis={{ kind:"numeric",column:"t",origin:null,start:0,end:forecast.horizon }} overlays={paths.slice(1).map((p,i) => ({ times:p.times,values:p.values[s.key],title:tr(p.action) || tr("Branch"),color:colors[i+1] }))} />)}
    <p className="ws-muted">{tr(forecast.uncertainty)}</p></div>;
}

export function ModelToolResult({ run }: { run: RuntimeRun }) {
  useLocale();
  const result = run.result as { trace?: { tool: string; result: Record<string, unknown> }[] };
  return <div>{result.trace?.map((trace,i) => <div key={i}><h3>{tr(trace.tool)}</h3><dl className="model-tool-values">{Object.entries(trace.result).map(([key,value]) => <div key={key}><dt>{tr(key)}</dt><dd>{typeof value === "number" ? number(value) : typeof value === "string" ? tr(value) : JSON.stringify(value)}</dd></div>)}</dl></div>)}</div>;
}
