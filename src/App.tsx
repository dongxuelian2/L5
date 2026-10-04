import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AnalystPanel, RootCauses } from "./components/Investigation";
import { ModelLab } from "./components/ModelLab";
import {
  AlarmInspector,
  Counterfactual,
  EvidenceInspector,
  Help,
  SignalInspector,
} from "./components/Overlays";
import {
  BlockBar,
  Count,
  Glyph,
  Panel,
  Reveal,
  ScrambleText,
  StatusDot,
} from "./components/Primitives";
import { ProcessMap } from "./components/ProcessMap";
import { Timeline } from "./components/Timeline";
import { TrendChart } from "./components/TrendChart";
import { IncidentStage, chapters } from "./components/IncidentStage";
import {
  CommandPalette,
  type WorkstationCommand,
} from "./components/CommandPalette";
import {
  alarmsAt,
  analyst,
  briefMarkdown,
  clock,
  downloadFile,
  pointAt,
  scenario,
  wallClock,
} from "./lib/engine";
import type { IncidentBrief, SignalKey } from "./types";

type View = "live" | "replay" | "lab";
type Overlay =
  | { type: "signal"; key: SignalKey }
  | { type: "evidence" }
  | { type: "alarms"; chain: string | null }
  | { type: "compare" }
  | { type: "help" }
  | { type: "commands" }
  | null;
const views: { id: View; symbol: string; label: string; key: string }[] = [
  { id: "live", symbol: "◉", label: "Live incident", key: "1" },
  { id: "replay", symbol: "↶", label: "Incident replay", key: "2" },
  { id: "lab", symbol: "⌗", label: "Computation lab", key: "3" },
];

export default function App() {
  const [view, setView] = useState<View>("live");
  const [time, setTime] = useState(180);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(6);
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [selectedCandidate, setSelectedCandidate] = useState("valve");
  const [brief, setBrief] = useState<IncidentBrief | null>(null);
  const [analysisStep, setAnalysisStep] = useState(0);
  const [analysisRunning, setAnalysisRunning] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [guided, setGuided] = useState(false);
  const [trendSignal, setTrendSignal] = useState<SignalKey | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [computationsOpen, setComputationsOpen] = useState(false);
  const request = useRef<AbortController | null>(null);
  const stepTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ready = time >= scenario.detections.purity.time;
  const alarms = useMemo(() => alarmsAt(time), [time]);
  const chainCount = scenario.chains.filter((c) =>
    alarms.some((a) => a.chain === c.id),
  ).length;
  const recentRate = alarms.filter((a) => a.t > time - 60).length;
  const alarmBins = Array.from({ length: 24 }, (_, i) => {
    const start = time - 120 + i * 5;
    return alarms.filter((alarm) => alarm.t > start && alarm.t <= start + 5)
      .length;
  });
  const maxBin = Math.max(1, ...alarmBins);
  const point = pointAt(time);
  const status =
    time < scenario.faultTime
      ? "NOMINAL"
      : time < scenario.firstAlarm
        ? "DEVIATION"
        : time < scenario.tripTime
          ? "ESCALATING"
          : "CRITICAL";
  const tone =
    time < scenario.faultTime
      ? "mint"
      : time < scenario.tripTime
        ? "amber"
        : "coral";
  const closeOverlay = useCallback(() => setOverlay(null), []);

  useEffect(() => {
    if (!playing) return;
    let previous = performance.now();
    const timer = setInterval(() => {
      const now = performance.now(),
        delta = ((now - previous) / 1000) * speed;
      previous = now;
      setTime((t) => Math.min(300, t + delta));
    }, 100);
    return () => clearInterval(timer);
  }, [playing, speed]);
  useEffect(() => {
    if (time >= 300) setPlaying(false);
  }, [time]);
  useEffect(() => {
    window.scrollTo(0, 0);
    if (view !== "live") {
      setPlaying(false);
      setGuided(false);
    }
  }, [view]);
  useEffect(
    () => () => {
      request.current?.abort();
      if (stepTimer.current) clearTimeout(stepTimer.current);
    },
    [],
  );
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(timer);
  }, [toast]);

  const runAnalysis = useCallback(async () => {
    request.current?.abort();
    if (stepTimer.current) clearTimeout(stepTimer.current);
    const controller = new AbortController();
    request.current = controller;
    setAnalysisRunning(true);
    setAnalysisStep(0);
    setAnalysisError(null);
    setBrief(null);
    try {
      const result = await analyst.analyze(
        scenario.analyst.prompt,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setBrief(result);
      // Progressively reveal the completed structured evidence, not model thinking.
      let step = 0;
      const reveal = () => {
        if (controller.signal.aborted) return;
        step++;
        setAnalysisStep(step);
        if (step < result.steps.length)
          stepTimer.current = setTimeout(reveal, 720);
        else {
          setAnalysisRunning(false);
          setToast("Investigation complete. The evidence is connected.");
        }
      };
      stepTimer.current = setTimeout(reveal, 720);
    } catch (error) {
      if (controller.signal.aborted) return;
      setAnalysisRunning(false);
      setAnalysisError(
        error instanceof Error
          ? error.message
          : "Unable to complete the investigation.",
      );
    }
  }, []);

  useEffect(() => {
    if (guided && time >= 80 && !brief && !analysisRunning && !analysisError)
      void runAnalysis();
  }, [guided, time, brief, analysisRunning, analysisError, runAnalysis]);

  const reset = useCallback((play = false) => {
    request.current?.abort();
    if (stepTimer.current) clearTimeout(stepTimer.current);
    setTime(0);
    setPlaying(play);
    setGuided(play);
    setBrief(null);
    setAnalysisRunning(false);
    setAnalysisError(null);
    setSelectedCandidate("valve");
    setOverlay(null);
  }, []);

  const seek = useCallback((next: number) => {
    setTime(next);
    setPlaying(false);
    setGuided(false);
    if (next < scenario.detections.purity.time) {
      request.current?.abort();
      if (stepTimer.current) clearTimeout(stepTimer.current);
      setBrief(null);
      setAnalysisRunning(false);
      setAnalysisError(null);
    }
  }, []);

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (!overlay || overlay.type === "commands") {
          setPlaying(false);
          setOverlay(
            overlay?.type === "commands" ? null : { type: "commands" },
          );
        }
        return;
      }
      if (
        overlay ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        (event.target instanceof Element &&
          event.target.closest(
            'input, textarea, select, button, summary, a, [role="button"], [contenteditable="true"]',
          ))
      )
        return;
      if (event.code === "Space") {
        event.preventDefault();
        if (time >= 300) reset(true);
        else setPlaying((p) => !p);
      }
      if (event.key === "1") setView("live");
      if (event.key === "2") setView("replay");
      if (event.key === "3") setView("lab");
      if (event.key.toLowerCase() === "r") reset(true);
      if (event.key === "?") setOverlay({ type: "help" });
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [overlay, reset, time]);

  function exportBrief() {
    if (!brief) return;
    downloadFile(
      "triplens-incident-001.md",
      briefMarkdown(brief),
      "text/markdown",
    );
    setToast("Incident brief exported.");
  }
  function changeView(next: View) {
    setView(next);
    if (next !== "live") {
      setPlaying(false);
      setGuided(false);
    }
  }

  const commands: WorkstationCommand[] = [
    ...views.map((item) => ({
      id: item.id,
      title: item.label,
      group: "WORKSPACE",
      hint: item.key,
      run: () => {
        closeOverlay();
        changeView(item.id);
      },
    })),
    {
      id: "run",
      title: "Run the complete incident sequence",
      group: "ACTION",
      hint: "R",
      keywords: "restart start play",
      run: () => {
        changeView("live");
        reset(true);
      },
    },
    {
      id: "investigate",
      title: "Investigate rising reactor pressure",
      group: "ACTION",
      hint: "↗",
      keywords: "analyst root cause why",
      disabled: !ready,
      run: () => {
        closeOverlay();
        changeView("live");
        void runAnalysis();
      },
    },
    {
      id: "compare",
      title: "Compare a cooling-bypass intervention",
      group: "ACTION",
      hint: "⑂",
      keywords: "counterfactual simulate branch",
      run: () => setOverlay({ type: "compare" }),
    },
    {
      id: "journal",
      title: "Open the alarm journal",
      group: "ACTION",
      hint: "↗",
      keywords: "logs raw events",
      run: () => setOverlay({ type: "alarms", chain: null }),
    },
    ...scenario.tags.map((tag) => ({
      id: tag.key,
      title: tag.name,
      group: "SIGNAL",
      hint: tag.tag,
      keywords: tag.tag,
      run: () => setOverlay({ type: "signal", key: tag.key }),
    })),
    ...chapters.map((chapter) => ({
      id: `chapter-${chapter.time}`,
      title: `Jump to ${chapter.label.toLowerCase()}`,
      group: "CHAPTER",
      hint: `+${clock(chapter.time)}`,
      keywords: chapter.title,
      run: () => {
        closeOverlay();
        changeView("replay");
        seek(chapter.time);
      },
    })),
  ];

  return (
    <div
      className={`workstation ${view === "lab" ? "is-lab" : "has-playback"}`}
    >
      <a href="#main-content" className="skip-link">
        Skip to workspace
      </a>
      <aside className="sidebar">
        <a
          href="#"
          className="brand"
          onClick={(event) => {
            event.preventDefault();
            changeView("live");
          }}
          aria-label="TripLens home"
        >
          <span className="brand-mark" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
          </span>
          <span>
            trip<span className="text-mint">lens</span>
            <small>INCIDENT INTELLIGENCE</small>
          </span>
        </a>
        <div className="workspace-label">
          WORKSPACE <span>/ 01</span>
        </div>
        <nav aria-label="Main navigation">
          {views.map((item) => (
            <button
              key={item.id}
              aria-label={item.label}
              aria-current={view === item.id ? "page" : undefined}
              className={`nav-item ${view === item.id ? "active" : ""}`}
              onClick={() => changeView(item.id)}
            >
              <Glyph>{item.symbol}</Glyph>
              <span>{item.label}</span>
              <kbd>{item.key}</kbd>
              {view === item.id && (
                <motion.span
                  className="nav-active-indicator"
                  layoutId="nav-indicator"
                />
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-divider" />
        <div className="workspace-label">
          CONNECTED PROCESS <span>⌁</span>
        </div>
        <div className="plant-card">
          <div>
            <StatusDot pulse={playing} />
            <strong>PROCESS / 01</strong>
          </div>
          <p>Reactor cooling loop</p>
          <div className="plant-tags">
            <span>6 signals</span>
            <span>5 paths</span>
          </div>
        </div>
        <div className="sidebar-tree">
          <div>
            <span className="tree-line">├─</span> R-101 <span>reactor</span>
            <i className={`bg-${time >= 41 ? "amber" : "mint"}`} />
          </div>
          <div>
            <span className="tree-line">├─</span> V-201 <span>separator</span>
            <i className={`bg-${time >= 56 ? "violet" : "mint"}`} />
          </div>
          <div>
            <span className="tree-line">└─</span> P-301 <span>product</span>
            <i className={`bg-${time >= 67 ? "violet" : "mint"}`} />
          </div>
        </div>
        <div className="sidebar-bottom">
          <div className="system-motif" aria-hidden="true">
            <span>░░░▒▒▓▓▒▒░░░░░░</span>
            <span>░▒▓██████▓▒░░░░</span>
            <span>▒██▓▒░░▒▓██▒░░░</span>
            <span>▓█▓░░◈░░░▓█▓░░░</span>
            <span>▒██▓▒░░▒▓██▒░░░</span>
            <span>░▒▓██████▓▒░░░░</span>
            <span>░░░▒▒▓▓▒▒░░░░░░</span>
          </div>
          <p>
            Less noise.
            <br />
            <span className="text-mint">More understanding.</span>
          </p>
          <button
            className="help-button"
            onClick={() => setOverlay({ type: "help" })}
          >
            <Glyph>?</Glyph> Field guide <kbd>?</kbd>
          </button>
          <div className="sidebar-version">
            <span>TRIPLENS / v0.1</span>
            <span className="text-mint">●</span>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <span className="text-mint">⌘</span>
            <span>workspace</span>
            <span>/</span>
            <strong>
              {view === "live"
                ? "live-incident"
                : view === "replay"
                  ? "incident-replay"
                  : "computation-lab"}
            </strong>
            <span className="terminal-cursor" aria-hidden="true">
              ▍
            </span>
          </div>
          <div className="topbar-right">
            <button
              className="command-trigger"
              aria-label="Open command palette"
              onClick={() => {
                setPlaying(false);
                setOverlay({ type: "commands" });
              }}
            >
              <span>⌕</span>
              <span>Jump to…</span>
              <kbd>Ctrl K</kbd>
            </button>
            <span className="connection-label">
              <StatusDot /> SYSTEM ONLINE
            </span>
            <span className="topbar-divider" />
            <time>
              {wallClock(time)} <span>UTC+08</span>
            </time>
            <button
              className="topbar-help"
              aria-label="Open field guide"
              onClick={() => setOverlay({ type: "help" })}
            >
              ?
            </button>
          </div>
        </header>
        <main id="main-content">
          <AnimatePresence mode="wait">
            <motion.div
              key={view}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -3 }}
              transition={{ duration: 0.2 }}
            >
              {view === "lab" ? (
                <ModelLab />
              ) : (
                <>
                  <div className="view-heading">
                    <div>
                      <div className="eyebrow">
                        <span className={`text-${tone}`}>●</span>{" "}
                        {view === "live"
                          ? "INCIDENT 001"
                          : "REPLAY / INCIDENT 001"}
                        <span className="heading-separator">/</span> COOLING
                        LOOP DISTURBANCE
                      </div>
                      <h1>
                        {view === "live"
                          ? "Every alarm has an origin"
                          : "Rewind the chain of events"}
                        <span className="text-mint">.</span>
                      </h1>
                      <p>
                        {view === "live"
                          ? "Trace the cascade. Find the first cause. Change the outcome."
                          : "Move through the incident. Watch the evidence emerge, one signal at a time."}
                      </p>
                    </div>
                    <div className="heading-actions">
                      <button
                        className="subtle-button bordered"
                        onClick={() => {
                          changeView("live");
                          reset(true);
                        }}
                      >
                        <Glyph>▷</Glyph> Run sequence
                      </button>
                      <button
                        className="primary-button"
                        onClick={() => {
                          setPlaying(false);
                          setOverlay({ type: "compare" });
                        }}
                      >
                        <Glyph>⑂</Glyph> Simulate intervention <Glyph>↗</Glyph>
                      </button>
                    </div>
                  </div>

                  {view === "replay" && (
                    <Reveal className="replay-banner">
                      <div>
                        <span className="text-violet">↶</span>
                        <strong>INC-001</strong>
                        <span>Cooling-water valve sticking</span>
                      </div>
                      <span>
                        05:00 duration · {scenario.alarms.length} events · 3
                        propagation chains
                      </span>
                    </Reveal>
                  )}

                  <Reveal delay={0.05}>
                    <section
                      className="incident-summary"
                      aria-label="Incident summary"
                    >
                      <button
                        className="summary-cell alarm-summary"
                        onClick={() =>
                          setOverlay({ type: "alarms", chain: null })
                        }
                      >
                        <span className="eyebrow">
                          RAW ALARM EVENTS <Glyph>↗</Glyph>
                        </span>
                        <div>
                          <strong className="text-coral">
                            <Count value={alarms.length} />
                          </strong>
                          <span className="mini-bars" aria-hidden="true">
                            {alarmBins.map((count, i) => (
                              <i
                                key={i}
                                style={{
                                  height: `${3 + (33 * count) / maxBin}px`,
                                  opacity: count ? 1 : 0.15,
                                }}
                              />
                            ))}
                          </span>
                        </div>
                        <span className="metric-caption">
                          {recentRate} events in the last 60s
                        </span>
                      </button>
                      <div className="summary-arrow" aria-hidden="true">
                        →
                      </div>
                      <button
                        aria-label="Inspect incident chains"
                        className="summary-cell chains-summary"
                        onClick={() =>
                          setOverlay({ type: "alarms", chain: "thermal" })
                        }
                      >
                        <span className="eyebrow">
                          INCIDENT CHAINS <Glyph>↗</Glyph>
                        </span>
                        <div>
                          <strong className="text-amber">0{chainCount}</strong>
                          <span className="chain-glyph" aria-hidden="true">
                            ┬────
                            <br />
                            ├────
                            <br />
                            └────
                          </span>
                        </div>
                        <span className="metric-caption">
                          Connected by time & topology
                        </span>
                      </button>
                      <div className="summary-arrow" aria-hidden="true">
                        →
                      </div>
                      <div className="summary-cell cause-summary">
                        <span className="eyebrow">LEADING ROOT CAUSE</span>
                        <div>
                          <strong className="text-mint">
                            {ready ? "01" : "—"}
                          </strong>
                          <span className="cause-name">
                            {ready ? (
                              <>
                                Cooling-water
                                <br />
                                valve sticking
                              </>
                            ) : (
                              <>
                                Collecting
                                <br />
                                signal evidence
                              </>
                            )}
                          </span>
                        </div>
                        <span className="metric-caption">
                          <span className="text-mint">
                            {ready ? "CV-101" : "LISTENING"}
                          </span>{" "}
                          {ready
                            ? "· upstream origin identified"
                            : "· awaiting propagation"}
                        </span>
                      </div>
                      <div className="summary-status">
                        <span className={`status-pill text-${tone}`}>
                          <StatusDot tone={tone} pulse={playing} />
                          <ScrambleText text={status} />
                        </span>
                        <div>
                          <span className="eyebrow">REACTOR PRESSURE</span>
                          <strong>
                            {Math.round(point.pressure).toLocaleString()}
                            <small>kPa</small>
                          </strong>
                        </div>
                        <span className="metric-caption">
                          TRIP LIMIT <span>3,050 kPa</span>
                        </span>
                      </div>
                    </section>
                  </Reveal>

                  <IncidentStage time={time} onSeek={seek} />
                  <div className="main-grid">
                    <Reveal delay={0.1}>
                      <ProcessMap
                        time={time}
                        selected={
                          overlay?.type === "signal" ? overlay.key : null
                        }
                        onSelect={(key) => {
                          setPlaying(false);
                          setOverlay({ type: "signal", key });
                        }}
                      />
                    </Reveal>
                    <Reveal delay={0.14}>
                      <RootCauses
                        ready={ready}
                        selected={selectedCandidate}
                        onSelect={setSelectedCandidate}
                        onInspect={() => setOverlay({ type: "evidence" })}
                      />
                    </Reveal>
                  </div>

                  <Reveal delay={0.18}>
                    <section
                      className="chain-strip"
                      aria-label="Incident chains"
                    >
                      <div className="chain-strip-label">
                        <span className="text-mint">⌁</span>
                        <span>THE CASCADE</span>
                      </div>
                      {scenario.chains.map((chain, i) => {
                        const count = alarms.filter(
                          (a) => a.chain === chain.id,
                        ).length;
                        return (
                          <button
                            key={chain.id}
                            className={`chain-item chain-${chain.color}`}
                            onClick={() =>
                              setOverlay({ type: "alarms", chain: chain.id })
                            }
                          >
                            <span className="chain-number">0{i + 1}</span>
                            <div>
                              <strong>{chain.name}</strong>
                              <span>
                                {chain.path
                                  .map(
                                    (key) =>
                                      scenario.tags.find((t) => t.key === key)!
                                        .tag,
                                  )
                                  .join(" → ")}
                              </span>
                            </div>
                            <span className="chain-count">
                              {count}
                              <small>events</small>
                            </span>
                            <Glyph>↗</Glyph>
                          </button>
                        );
                      })}
                    </section>
                  </Reveal>

                  <div className="main-grid bottom-grid">
                    <Reveal delay={0.22}>
                      <Panel
                        code="03"
                        title="Signal historian"
                        className="historian-panel"
                        action={
                          <span className="panel-meta">
                            {trendSignal
                              ? "absolute values"
                              : "normalized per signal"}{" "}
                            / 1s
                          </span>
                        }
                      >
                        <div className="chart-legend">
                          {(
                            ["pressure", "temperature", "flow"] as SignalKey[]
                          ).map((key) => {
                            const tag = scenario.tags.find(
                              (t) => t.key === key,
                            )!;
                            return (
                              <button
                                key={key}
                                className={`${trendSignal === key ? "selected" : ""} text-${tag.color}`}
                                onClick={() =>
                                  setTrendSignal((s) =>
                                    s === key ? null : key,
                                  )
                                }
                              >
                                <i className={`bg-${tag.color}`} />
                                {tag.name}
                                <span>{point[key].toFixed(tag.precision)}</span>
                              </button>
                            );
                          })}
                        </div>
                        <TrendChart
                          keys={
                            trendSignal
                              ? [trendSignal]
                              : ["pressure", "temperature", "flow"]
                          }
                          time={Math.floor(time)}
                          onSeek={seek}
                        />
                        <div className="historian-bottom">
                          <span>
                            <span className="text-mint">┊</span> Fault injected
                            +00:30
                          </span>
                          <span>
                            Valve deviation{" "}
                            <strong className="text-mint">+00:33</strong>
                          </span>
                          <button
                            className="text-button"
                            onClick={() => setComputationsOpen((open) => !open)}
                          >
                            {computationsOpen ? "Hide" : "Live"} calculations{" "}
                            {computationsOpen ? "−" : "+"}
                          </button>
                        </div>
                      </Panel>
                    </Reveal>
                    <Reveal delay={0.26}>
                      <AnalystPanel
                        brief={brief}
                        step={analysisStep}
                        running={analysisRunning}
                        error={analysisError}
                        onRun={() => void runAnalysis()}
                        onExport={exportBrief}
                        onCompare={() => setOverlay({ type: "compare" })}
                        ready={ready}
                      />
                    </Reveal>
                  </div>

                  <AnimatePresence>
                    {computationsOpen && (
                      <motion.section
                        className="live-computations"
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                      >
                        <div className="live-computation-heading">
                          <span className="eyebrow text-mint">
                            ƒ LIVE SIGNAL CALCULATIONS
                          </span>
                          <span className="muted">
                            z = (x − median) / (1.4826 × MAD)
                          </span>
                        </div>
                        <div className="computation-signals">
                          {scenario.tags.map((tag) => {
                            const d =
                              scenario.diagnostics.streams[Math.floor(time)]
                                .signals[tag.key];
                            return (
                              <button
                                key={tag.key}
                                onClick={() =>
                                  setOverlay({ type: "signal", key: tag.key })
                                }
                              >
                                <strong className={`text-${tag.color}`}>
                                  {tag.tag}
                                </strong>
                                <span>
                                  robust z <b>{d.z.toFixed(1)}</b>
                                </span>
                                <span>
                                  CUSUM <b>{d.cusum.toFixed(0)}</b>
                                </span>
                                <span>
                                  Δ / s <b>{d.delta.toFixed(2)}</b>
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      </motion.section>
                    )}
                  </AnimatePresence>

                  <div className="event-ribbon">
                    <span className="eyebrow">LATEST EVENT</span>
                    <span className="text-muted">
                      {alarms.length
                        ? wallClock(alarms[alarms.length - 1].t)
                        : wallClock(time)}
                    </span>
                    <span className="text-amber">
                      {alarms.length ? alarms[alarms.length - 1].tag : "SYSTEM"}
                    </span>
                    <span>
                      {alarms.length
                        ? alarms[alarms.length - 1].message
                        : "All process signals within baseline. Awaiting disturbance."}
                    </span>
                    <button
                      onClick={() =>
                        setOverlay({ type: "alarms", chain: null })
                      }
                    >
                      Open journal ↗
                    </button>
                  </div>
                </>
              )}
            </motion.div>
          </AnimatePresence>
        </main>
        {view !== "lab" && (
          <div className="playback-dock">
            <Timeline
              time={time}
              playing={playing}
              speed={speed}
              onSeek={seek}
              onToggle={() => {
                if (time >= 300) reset(true);
                else setPlaying((p) => !p);
              }}
              onSpeed={() =>
                setSpeed((s) => (s === 1 ? 3 : s === 3 ? 6 : s === 6 ? 12 : 1))
              }
              onReset={() => reset()}
            />
          </div>
        )}
        <footer className="statusbar">
          <div>
            <span className="text-mint">❯</span>
            <strong>triplens</strong>
            <span className="statusbar-path">~/process-01</span>
            <span className="text-mint">●</span>
            <span>{playing ? "streaming" : "snapshot"}</span>
            <span className="statusbar-mode">
              {view === "lab"
                ? "COMPUTE"
                : view === "replay"
                  ? "REPLAY"
                  : "OBSERVE"}
            </span>
          </div>
          <div>
            <span>Δt 1s</span>
            <span>{Math.floor(time) + 1}/301 samples</span>
            <BlockBar value={time / 300} count={12} />
            <span className="desktop-only">evidence before inference</span>
          </div>
        </footer>
      </div>

      <AnimatePresence mode="wait">
        {overlay?.type === "commands" && (
          <CommandPalette
            key="commands"
            commands={commands}
            onClose={closeOverlay}
          />
        )}
        {overlay?.type === "signal" && (
          <SignalInspector
            key={`signal-${overlay.key}`}
            signal={overlay.key}
            time={time}
            onClose={closeOverlay}
          />
        )}
        {overlay?.type === "evidence" && (
          <EvidenceInspector
            key="evidence"
            candidateId={selectedCandidate}
            onClose={closeOverlay}
          />
        )}
        {overlay?.type === "alarms" && (
          <AlarmInspector
            key="alarms"
            time={time}
            chainId={overlay.chain}
            onClose={closeOverlay}
          />
        )}
        {overlay?.type === "compare" && (
          <Counterfactual key="compare" onClose={closeOverlay} />
        )}
        {overlay?.type === "help" && <Help key="help" onClose={closeOverlay} />}
      </AnimatePresence>
      <AnimatePresence>
        {toast && (
          <motion.div
            className="toast"
            role="status"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 6 }}
          >
            <span className="text-mint">✓</span>
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
