import { useState } from "react";
import { t as tr } from "../../lib/text";
import { detectorName } from "./RegimeSetup";
import type { RegimeModel } from "./regimeTypes";
import { number, timeLabel, type Dataset } from "../types";

export function modeLabel(model: RegimeModel, id: string | null) {
  return id ? model.config.modes.find(mode => mode.id === id)?.label || id : "—";
}

export function RegimeModelView({ model, datasets }: { model: RegimeModel; datasets: Dataset[] }) {
  const { config } = model, channels = config.recognition.recognitionSignals;
  const [pair, setPair] = useState(0);
  const [against, setAgainst] = useState(0);
  const comparison = model.model.comparisons[pair];
  return <section className="ws-panel regime-model-view" aria-label={"Frozen model evidence"}>
    <div className="regime-heading"><h2>Frozen model evidence</h2><span className="ws-muted">{tr("{0} operating modes", { 0: config.modes.length })}</span></div>
    <div className="regime-model-cards">
      {config.modes.map((mode, index) => {
        const fitted = model.model.modes[mode.id];
        return <article className="regime-model-card" key={mode.id}>
          <h3><i className="regime-swatch" style={{ background: regimeColors[index % regimeColors.length] }} />{mode.label}</h3>
          <dl className="regime-stat-list">
            <div><dt>Fit samples</dt><dd>{fitted.fitSamples.toLocaleString("en")}</dd></div>
            <div><dt>Calibration samples</dt><dd>{fitted.calibrationSamples.toLocaleString("en")}</dd></div>
            <div><dt>Support distance limit</dt><dd>{number(fitted.distanceThreshold)}</dd></div>
            <div><dt>{detectorName(fitted.detector.algorithm)} · Alarm threshold</dt><dd>{number(fitted.detector.threshold)}</dd></div>
          </dl>
          <details><summary>Source windows</summary><ul className="regime-source-list">
            {(["fit", "calibration"] as const).flatMap(role => mode[role].map((ref, index) => {
              const dataset = datasets.find(item => item.id === ref.datasetId);
              const span = dataset ? ref.range.map(time => timeLabel(dataset.metadata.time, time)).join(" → ") : `${ref.range.map(number).join(" → ")} s`;
              return <li key={`${role}-${index}`}><span>{tr(role === "fit" ? "Fit" : "Calibration")}</span> {dataset?.name ?? ref.datasetId} · {span}</li>;
            }))}
          </ul></details>
          <details><summary>Location and covariance</summary>
            <label>Covariance with<select value={against} onChange={e => setAgainst(Number(e.target.value))}>{channels.map((signal, i) => <option key={signal} value={i}>{signal}</option>)}</select></label>
            <div className="ws-table-scroll"><table>
              <thead><tr><th>Recognition signal</th><th>Mean</th><th>Variance</th><th>Covariance</th></tr></thead>
              <tbody>{channels.map((signal, i) => <tr key={signal}><th scope="row">{signal}</th><td>{number(fitted.center[i])}</td><td>{number(fitted.covariance[i][i])}</td><td>{number(fitted.covariance[i][against])}</td></tr>)}</tbody>
            </table></div>
          </details>
        </article>;
      })}
    </div>
    {comparison && <div className="regime-comparison-model">
      <div className="regime-heading"><h3>Between-mode distribution differences</h3></div>
      <label>Compare modes<select value={pair} onChange={e => setPair(Number(e.target.value))}>
        {model.model.comparisons.map((item, i) => <option key={i} value={i}>{modeLabel(model, item.fromMode)} → {modeLabel(model, item.toMode)}</option>)}
      </select></label>
      <p>Center separation in pooled within-mode scale <strong>{number(comparison.meanDistance)}</strong></p>
      <p>Regularized covariance distance <strong>{number(comparison.covarianceDistance)}</strong></p>
      <div className="ws-table-scroll"><table>
        <thead><tr><th>Signal</th><th>Mean difference</th><th>Standardized difference</th></tr></thead>
        <tbody>{comparison.signals.map(item => <tr key={item.signal}><th scope="row">{item.signal}</th><td>{number(item.meanDifference)}</td><td>{number(item.standardizedDifference)}</td></tr>)}</tbody>
      </table></div>
    </div>}
  </section>;
}

export const regimeColors = ["#b5ed9a", "#8cbfe8", "#c6a5e0", "#e4bb75", "#80cfbe", "#f3a8a0", "#d3d982", "#9caae5"];
