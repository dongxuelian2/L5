import { useState } from "react";
import { downloadFile, scenario } from "../lib/engine";
import { BlockBar, Panel, Reveal } from "./Primitives";

export function ModelLab() {
  const [selected, setSelected] = useState("valve");
  const [inspectCell, setInspectCell] = useState<[number, number]>([1, 2]);
  const ranking = scenario.diagnostics.ranking[selected];
  const [a, b] = inspectCell;
  const passedChecks = scenario.checks.filter((check) => check.passed).length;
  const orderedPaths = scenario.diagnostics.paths.filter(
    (path) => path.ordered,
  ).length;
  return (
    <div className="lab-view">
      <Reveal>
        <div className="view-heading">
          <div>
            <div className="eyebrow text-mint">
              COMPUTATION / TRANSPARENT BY DESIGN
            </div>
            <h1>
              See the work behind the answer<span className="text-mint">.</span>
            </h1>
            <p>
              Signal statistics, physical paths, and reproducible checks. Every
              number has a source.
            </p>
          </div>
          <button
            className="subtle-button bordered"
            onClick={() =>
              downloadFile(
                "triplens-diagnostics.json",
                JSON.stringify(scenario.diagnostics, null, 2),
              )
            }
          >
            Export calculations ↓
          </button>
        </div>
      </Reveal>
      <div className="lab-summary">
        <div>
          <span className="eyebrow">SIGNALS ANALYZED</span>
          <strong>
            {String(scenario.tags.length).padStart(2, "0")}
            <span> / {scenario.points.length} samples each</span>
          </strong>
        </div>
        <div>
          <span className="eyebrow">ORDERED PATHS</span>
          <strong>
            {String(orderedPaths).padStart(2, "0")}
            <span>
              {" "}
              / {String(scenario.edges.length).padStart(2, "0")} topology edges
            </span>
          </strong>
        </div>
        <div>
          <span className="eyebrow">REPRODUCIBILITY</span>
          <strong className="text-mint">
            {String(passedChecks).padStart(2, "0")}
            <span>
              {" "}
              / {String(scenario.checks.length).padStart(2, "0")} checks passed
            </span>
          </strong>
        </div>
      </div>
      <div className="lab-grid">
        <Panel
          code="Σ"
          title="Signal correlation matrix"
          action={<span className="panel-meta">Pearson r · full incident</span>}
        >
          <div className="matrix-wrap">
            <div className="correlation-matrix">
              <span />
              {scenario.tags.map((t) => (
                <span className="matrix-label" key={t.key}>
                  {t.tag}
                </span>
              ))}
              {scenario.tags.map((t, i) => (
                <div className="matrix-row" key={t.key}>
                  <span className="matrix-label">{t.tag}</span>
                  {scenario.tags.map((u, j) => {
                    const value = scenario.diagnostics.matrix[i][j];
                    return (
                      <button
                        key={u.key}
                        aria-label={`${t.name} and ${u.name}: correlation ${value}`}
                        className={a === i && b === j ? "selected" : ""}
                        style={{
                          background:
                            value >= 0
                              ? `rgba(181,237,154,${Math.abs(value) * 0.27 + 0.015})`
                              : `rgba(180,160,219,${Math.abs(value) * 0.26 + 0.015})`,
                          color: value >= 0 ? "#c8e4b9" : "#c7b6e1",
                        }}
                        onClick={() => setInspectCell([i, j])}
                      >
                        {value.toFixed(2)}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
            <div className="matrix-key">
              <span className="text-violet">−1.0 inverse</span>
              <span>0 unrelated</span>
              <span className="text-mint">+1.0 aligned</span>
            </div>
          </div>
          <div className="matrix-detail">
            <span>
              {scenario.tags[a].tag} <span className="muted">×</span>{" "}
              {scenario.tags[b].tag}
            </span>
            <strong>{scenario.diagnostics.matrix[a][b].toFixed(4)}</strong>
            <p>
              Correlation describes co-movement. The diagnosis also requires
              connected process topology and temporal precedence.
            </p>
          </div>
        </Panel>
        <Panel
          code="ƒ"
          title="Root-cause score decomposition"
          action={<span className="panel-meta">explicit rules</span>}
        >
          <div className="score-body">
            <div className="filter-tabs score-tabs">
              {scenario.candidates.map((c, i) => (
                <button
                  key={c.id}
                  className={selected === c.id ? "selected" : ""}
                  onClick={() => setSelected(c.id)}
                >
                  0{i + 1} / {c.tag}
                </button>
              ))}
            </div>
            <div className="score-formula">S(c) = D + C + T − U − M</div>
            {[
              ["Signal direction", "direction", 40],
              ["Topology coverage", "coverage", 35],
              ["Ordered paths", "temporal", 25],
              ["Unexplained signals", "unexplainedPenalty", 40],
              ["Missing command feedback", "missingFeedbackPenalty", 6],
            ].map(([name, key, max], i) => (
              <div className="score-row" key={key}>
                <span>{name}</span>
                <BlockBar
                  value={ranking.parts[key] / Number(max)}
                  color={i >= 3 ? "amber" : "mint"}
                  count={16}
                />
                <strong className={i >= 3 ? "text-amber" : "text-mint"}>
                  {i >= 3 ? "−" : "+"}
                  {ranking.parts[key]}
                </strong>
              </div>
            ))}
            <div className="score-total">
              <span>Resulting evidence score</span>
              <strong>
                {ranking.score}
                <small> / 100</small>
              </strong>
            </div>
            <p className="muted small-copy">
              {ranking.explained}/6 signals explained · {ranking.paths}/5
              supported paths. Scores are clamped to 0–100. Hypothesis
              signatures and weights are explicit engineering choices.
            </p>
          </div>
        </Panel>
        <Panel
          code="Δ"
          title="Propagation evidence"
          action={<span className="panel-meta">topology constrained</span>}
        >
          <div className="propagation-table">
            <div className="propagation-head">
              <span>DIRECTED EDGE</span>
              <span>ONSET LAG</span>
              <span>LAGGED r</span>
              <span>ORDER</span>
            </div>
            {scenario.diagnostics.paths.map((p) => (
              <div key={p.source}>
                <span>
                  {scenario.tags.find((t) => t.key === p.source)!.tag}
                  <span className="text-mint"> → </span>
                  {scenario.tags.find((t) => t.key === p.target)!.tag}
                </span>
                <span>+{p.lag}s</span>
                <span
                  className={p.correlation < 0 ? "text-violet" : "text-mint"}
                >
                  {p.correlation.toFixed(3)}
                </span>
                <span className="text-mint">✓</span>
              </div>
            ))}
          </div>
          <div className="lab-note">
            Lag is the difference in confirmed detection times. Correlation uses
            that shift and does not estimate an independent causal effect.
          </div>
        </Panel>
        <Panel
          code="✓"
          title="Reproducibility checks"
          action={
            <span className="panel-meta text-mint">
              {passedChecks === scenario.checks.length
                ? "all passed"
                : "review needed"}
            </span>
          }
        >
          <div className="check-list">
            {scenario.checks.map((check) => (
              <div key={check.name}>
                <span className="check-icon">{check.passed ? "✓" : "!"}</span>
                <div>
                  <strong>{check.name}</strong>
                  <p>{check.detail}</p>
                </div>
                <span className="check-pass">
                  {check.passed ? "PASS" : "FAIL"}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
      <div className="lab-source">
        <span className="text-mint">⌘</span>
        <div>
          <strong>Calculation provenance</strong>
          <p>
            Native Python · reduced-order process model · 1 s Euler integration
            · median/MAD detection · JSON artifacts. These checks cover this
            single scenario and its three branches; they are not a benchmark
            accuracy claim.
          </p>
        </div>
        <span className="source-file">simulation/generate.py</span>
      </div>
    </div>
  );
}
