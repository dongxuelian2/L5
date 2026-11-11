import { useEffect, useState } from "react";
import { t as tr, useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { api, go, message } from "./api";
import { LiveEvidence, sampleDate } from "./LiveEvidence";
import { LiveBrowser, LiveConnection, LiveMappings } from "./LiveSetup";
import type { LiveConfig, LiveMappingDraft, LiveNode, LiveSession, LiveStatus } from "./liveTypes";
import type { CatalogSignal, Dataset } from "./types";
import "./live.css";

export function LiveWorkspace({ workspaceId, sessionId, onDataset }: {
  workspaceId: string;
  sessionId?: string;
  onDataset: (dataset: Dataset) => void;
}) {
  useLocale();
  const route = `workspaces/${workspaceId}/live`;
  const prefix = `/${route}`;
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [sessions, setSessions] = useState<LiveSession[]>([]);
  const [opened, setOpened] = useState<LiveSession | null>(null);
  const [catalog, setCatalog] = useState<CatalogSignal[]>([]);
  const [mappings, setMappings] = useState<LiveMappingDraft[]>([]);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [statusError, setStatusError] = useState("");
  const [sessionError, setSessionError] = useState("");
  const [catalogError, setCatalogError] = useState("");
  const activeId = status?.active_session_id;
  const connected = status?.connection_state === "connected";
  const selectedId = sessionId || activeId || sessions[0]?.id;
  const selectedSession = opened?.id === selectedId ? opened : sessions.find(session => session.id === selectedId);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    async function update() {
      try {
        const next = await api<LiveStatus>(`${prefix}/status`, undefined, "GET", controller.signal);
        if (!controller.signal.aborted) {
          setStatus(next);
          setStatusError("");
        }
      } catch (e) {
        if (!controller.signal.aborted) setStatusError(message(e));
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(update, 1500);
      }
    }
    void update();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [prefix, revision]);

  useEffect(() => {
    const controller = new AbortController();
    api<{ sessions: LiveSession[] }>(`${prefix}/sessions`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) { setSessions(data.sessions); setSessionError(""); } })
      .catch(e => { if (!controller.signal.aborted) setSessionError(message(e)); });
    return () => controller.abort();
  }, [prefix, activeId, revision]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    api<LiveSession>(`${prefix}/sessions/${selectedId}`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) { setOpened(data); setSessionError(""); } })
      .catch(e => { if (!controller.signal.aborted) setSessionError(message(e)); });
    return () => controller.abort();
  }, [prefix, selectedId, activeId, revision]);

  useEffect(() => {
    if (!connected || activeId) return;
    const controller = new AbortController();
    api<{ signals: CatalogSignal[] }>(`/workspaces/${workspaceId}/signals`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) { setCatalog(data.signals); setCatalogError(""); } })
      .catch(e => { if (!controller.signal.aborted) setCatalogError(message(e)); });
    return () => controller.abort();
  }, [workspaceId, connected, activeId]);

  async function command(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(message(e));
    } finally {
      setRevision(current => current + 1);
      setBusy(false);
    }
  }

  function selectSession(id: string) {
    setSessionError("");
    go(`${route}/${id}`);
  }

  function saveSession(session: LiveSession) {
    setSessions(current => [session, ...current.filter(item => item.id !== session.id)]);
    setOpened(session);
    selectSession(session.id);
  }

  function connect(config: LiveConfig) {
    return command(async () => {
      const next = await api<LiveStatus>(`${prefix}/connect`, config);
      if (status?.config?.endpoint !== next.config?.endpoint) setMappings([]);
      setStatus(next);
    });
  }

  function disconnect() {
    return command(async () => {
      setStatus(await api<LiveStatus>(`${prefix}/disconnect`, {}));
      setMappings([]);
    });
  }

  function start(name: string) {
    return command(async () => {
      const session = await api<LiveSession>(`${prefix}/sessions`, { name, mappings });
      setStatus(current => current && { ...current, active_session_id: session.id });
      saveSession(session);
    });
  }

  function stop() {
    if (!activeId) return;
    return command(async () => {
      const session = await api<LiveSession>(`${prefix}/sessions/${activeId}/stop`, {});
      setStatus(current => current && { ...current, active_session_id: null });
      saveSession(session);
    });
  }

  function toggle(node: LiveNode) {
    setMappings(current => current.some(mapping => mapping.node_id === node.node_id)
      ? current.filter(mapping => mapping.node_id !== node.node_id)
      : [...current, { node_id: node.node_id, display_name: node.display_name, unit: node.unit || "", data_type: node.data_type, namespace_uri: node.namespace_uri }]);
  }

  return <>
    <div className="ws-page-title"><div>
      <h1>{tr("Live data")}<span className="ws-accent">.</span></h1>
      <p>{tr("Record OPC UA measurements with timestamps and quality. Save a recording as a dataset for analysis.")}</p>
    </div></div>
    {statusError && <p className="ws-error" role="alert">{errorMessage(statusError)}</p>}
    {error && error !== status?.last_error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {status ? <LiveConnection status={status} busy={busy || Boolean(statusError)} connect={connect} disconnect={() => void disconnect()} stop={() => void stop()} openRecording={() => { if (activeId) selectSession(activeId); }} />
      : !statusError && <p role="status">{tr("Checking OPC UA connection…")}</p>}
    {connected && !activeId && <>
      <LiveBrowser key={status?.config?.endpoint} prefix={prefix} enabled={!busy && !statusError} mappings={mappings} toggle={toggle} />
      {catalogError && <p className="ws-error" role="alert">{errorMessage(catalogError)}</p>}
      <LiveMappings
        mappings={mappings}
        catalog={catalog}
        busy={busy || Boolean(statusError)}
        update={mapping => setMappings(current => current.map(item => item.node_id === mapping.node_id ? mapping : item))}
        remove={nodeId => setMappings(current => current.filter(item => item.node_id !== nodeId))}
        start={name => void start(name)}
      />
    </>}
    <section className="ws-panel live-panel" aria-labelledby="live-recordings-title">
      <div className="ws-section-heading"><h2 id="live-recordings-title">{tr("Acquisition recordings")}</h2><span className="ws-muted">{sessions.length.toLocaleString()}</span></div>
      {sessionError && <p className="ws-error" role="alert">{errorMessage(sessionError)}</p>}
      {sessions.length > 0 ? <label>{tr("Open a recording")}
        <select value={selectedId || ""} onChange={e => selectSession(e.target.value)}>
          {!sessions.some(session => session.id === selectedId) && <option value={selectedId || ""} disabled>{tr("Choose a recording")}</option>}
          {sessions.map(session => <option key={session.id} value={session.id}>{session.name} · {tr(`live.session.${session.state}`)} · {sampleDate(session.started_at)}</option>)}
        </select>
      </label> : !sessionError && <p className="live-hint">{tr("Recordings will appear here when acquisition starts.")}</p>}
    </section>
    {selectedSession && <LiveEvidence key={selectedSession.id} prefix={prefix} session={selectedSession} onDataset={onDataset} />}
  </>;
}
