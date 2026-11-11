import { useEffect, useRef, useState, type FormEvent } from "react";
import { t as tr } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { api, message } from "./api";
import { LiveQuality, readingValue, sampleDate } from "./LiveEvidence";
import { signalLabel, type CatalogSignal } from "./types";
import type { LiveConfig, LiveMappingDraft, LiveNode, LiveReading, LiveSecurityMode, LiveStatus } from "./liveTypes";

const defaults: LiveConfig = {
  endpoint: "opc.tcp://127.0.0.1:4840/l5/tanks/",
  security_mode: "none",
  sampling_interval_ms: 250,
  publishing_interval_ms: 250,
  timeout_seconds: 3,
  buffer_capacity: 4096,
};

export function LiveConnection({ status, busy, connect, disconnect, stop, openRecording }: {
  status: LiveStatus;
  busy: boolean;
  connect: (config: LiveConfig) => Promise<void>;
  disconnect: () => void;
  stop: () => void;
  openRecording: () => void;
}) {
  const [form, setForm] = useState<LiveConfig>(() => ({ ...defaults, ...status.config }));
  const connected = status.connection_state === "connected";
  const active = Boolean(status.active_session_id);
  const configured = connected || active;
  const secured = form.security_mode !== "none";
  const encrypted = form.security_mode === "sign_and_encrypt";
  function set<K extends keyof LiveConfig>(key: K, value: LiveConfig[K]) {
    setForm(current => ({ ...current, [key]: value }));
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    const config = {
      endpoint: form.endpoint.trim(),
      security_mode: form.security_mode,
      sampling_interval_ms: form.sampling_interval_ms,
      publishing_interval_ms: form.publishing_interval_ms,
      timeout_seconds: form.timeout_seconds,
      buffer_capacity: form.buffer_capacity,
      ...(secured ? {
        application_uri: form.application_uri?.trim() || undefined,
        client_certificate: form.client_certificate?.trim(),
        client_private_key: form.client_private_key?.trim(),
        server_certificate: form.server_certificate?.trim(),
        private_key_password: form.private_key_password || undefined,
      } : {}),
      ...(encrypted && form.username?.trim() ? { username: form.username.trim(), password: form.password } : {}),
    };
    setForm(current => ({ ...current, password: "", private_key_password: "" }));
    await connect(config);
  }
  return <section className="ws-panel live-panel" aria-labelledby="live-connection-title">
    <div className="ws-section-heading">
      <h2 id="live-connection-title">{tr("OPC UA connection")}</h2>
      <span className="live-state" data-state={status.connection_state} role="status"><i />{tr(`live.connection.${status.connection_state}`)}</span>
    </div>
    {status.last_error && <p className="ws-error" role="alert">{errorMessage(status.last_error)}</p>}
    {configured ? <>
      <dl className="live-connection-facts">
        <div><dt>{tr("Server endpoint")}</dt><dd>{status.config?.endpoint || "—"}</dd></div>
        <div><dt>{tr("Security mode")}</dt><dd>{status.config ? tr(`live.security.${status.config.security_mode}`) : "—"}</dd></div>
        <div><dt>{tr("Sampling / publishing")}</dt><dd>{status.config ? `${status.config.sampling_interval_ms} / ${status.config.publishing_interval_ms} ms` : "—"}</dd></div>
        {active && <>
          <div><dt>{tr("Buffered observations")}</dt><dd>{status.buffered?.toLocaleString() ?? "—"}</dd></div>
          <div><dt>{tr("Dropped observations")}</dt><dd className={status.dropped ? "ws-coral" : ""}>{status.dropped?.toLocaleString() ?? "—"}</dd></div>
          <div><dt>{tr("Last notification (UTC)")}</dt><dd>{sampleDate(status.last_notification_at)}</dd></div>
        </>}
      </dl>
      <div className="ws-inline live-actions">
        {active ? <>
          <button className="ws-primary" type="button" onClick={stop} disabled={busy}>{tr("Stop and save recording")}</button>
          <button className="ws-outlined" type="button" onClick={openRecording}>{tr("View active recording")}</button>
        </> : <button className="ws-outlined" type="button" onClick={disconnect} disabled={busy}>{tr("Disconnect")}</button>}
      </div>
    </> : <form onSubmit={e => void submit(e)} autoComplete="off">
      <div className="ws-form-grid live-connection-fields">
        <label>{tr("Server endpoint")}<input value={form.endpoint} onChange={e => set("endpoint", e.target.value)} required placeholder={defaults.endpoint} autoCapitalize="off" spellCheck={false} /></label>
        <label>{tr("Security mode")}<select value={form.security_mode} onChange={e => set("security_mode", e.target.value as LiveSecurityMode)}>
          {(["none", "sign", "sign_and_encrypt"] as const).map(mode => <option key={mode} value={mode}>{tr(`live.security.${mode}`)}</option>)}
        </select></label>
        <label>{tr("Sampling interval (ms)")}<input type="number" min={10} max={60000} step="any" value={form.sampling_interval_ms || ""} onChange={e => set("sampling_interval_ms", e.target.valueAsNumber)} required /></label>
        <label>{tr("Publishing interval (ms)")}<input type="number" min={10} max={60000} step="any" value={form.publishing_interval_ms || ""} onChange={e => set("publishing_interval_ms", e.target.valueAsNumber)} required /></label>
      </div>
      {secured && <fieldset>
        <legend>{tr("Certificates on the L5 host")}</legend>
        <p className="ws-muted">{tr("Enter local file paths. Use a trusted copy of the server certificate.")}</p>
        <div className="ws-form-grid">
          <label>{tr("Server certificate path")}<input value={form.server_certificate || ""} onChange={e => set("server_certificate", e.target.value)} required /></label>
          <label>{tr("Client certificate path")}<input value={form.client_certificate || ""} onChange={e => set("client_certificate", e.target.value)} required /></label>
          <label>{tr("Client private key path")}<input value={form.client_private_key || ""} onChange={e => set("client_private_key", e.target.value)} required /></label>
          <label>{tr("Private key password (optional)")}<input type="password" autoComplete="new-password" value={form.private_key_password || ""} onChange={e => set("private_key_password", e.target.value)} /></label>
          <label>{tr("Client application URI (optional)")}<input value={form.application_uri || ""} onChange={e => set("application_uri", e.target.value)} /></label>
        </div>
      </fieldset>}
      {encrypted && <div className="ws-form-grid">
        <label>{tr("Username (optional)")}<input value={form.username || ""} onChange={e => set("username", e.target.value)} autoComplete="off" /></label>
        <label>{tr("Password")}<input type="password" autoComplete="new-password" required={Boolean(form.username?.trim())} disabled={!form.username?.trim()} value={form.password || ""} onChange={e => set("password", e.target.value)} /></label>
      </div>}
      <details>
        <summary>{tr("Connection and buffer settings")}</summary>
        <div className="ws-form-grid">
          <label>{tr("Request timeout (s)")}<input type="number" min={0.25} max={30} step="any" value={form.timeout_seconds || ""} onChange={e => set("timeout_seconds", e.target.valueAsNumber)} required /></label>
          <label>{tr("Buffer capacity (observations)")}<input type="number" min={1} max={50000} value={form.buffer_capacity || ""} onChange={e => set("buffer_capacity", e.target.valueAsNumber)} required /></label>
        </div>
      </details>
      <button className="ws-primary" disabled={busy || status.connection_state === "connecting" || !form.endpoint.trim()}>{tr(busy || status.connection_state === "connecting" ? "Connecting…" : "Connect")}</button>
    </form>}
  </section>;
}

type BrowseLocation = Pick<LiveNode, "node_id" | "display_name">;
type BrowseState = { path: BrowseLocation[]; nodes: LiveNode[] };
type ReadingState = { node: LiveNode; sample: LiveReading };

export function LiveBrowser({ prefix, enabled, mappings, toggle }: {
  prefix: string;
  enabled: boolean;
  mappings: LiveMappingDraft[];
  toggle: (node: LiveNode) => void;
}) {
  const [tree, setTree] = useState<BrowseState>({ path: [], nodes: [] });
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [reading, setReading] = useState<ReadingState | null>(null);
  const [filter, setFilter] = useState("");
  const [nodeId, setNodeId] = useState("");
  const request = useRef<AbortController | null>(null);
  const target = tree.path.at(-1);
  function perform<T>(label: string, route: string, setData: (value: T) => void) {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setPending(label);
    setError("");
    api<T>(`${prefix}/${route}`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) setData(data); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setPending(""); });
  }
  function browse(path: BrowseLocation[]) {
    const parent = path.at(-1);
    perform<{ nodes: LiveNode[] }>("browse", `browse${parent ? `?${new URLSearchParams({ node_id: parent.node_id })}` : ""}`, data => {
      setTree({ path, nodes: data.nodes });
      setFilter("");
    });
  }
  useEffect(() => {
    if (enabled) browse(tree.path);
    else setPending("");
    return () => request.current?.abort();
  }, [enabled, prefix]);
  function read(node: LiveNode) {
    setReading(null);
    perform<LiveReading>(node.node_id, `read?${new URLSearchParams({ node_id: node.node_id })}`, sample => setReading({ node, sample }));
  }
  const needle = filter.trim().toLowerCase();
  const nodes = tree.nodes.filter(node => `${node.display_name} ${node.node_id}`.toLowerCase().includes(needle));
  const unavailable = Boolean(pending) || !enabled;
  return <section className="ws-panel live-panel" aria-labelledby="live-browse-title">
    <div className="ws-section-heading"><h2 id="live-browse-title">{tr("Browse OPC UA nodes")}</h2>
      <button className="ws-outlined" type="button" disabled={unavailable} onClick={() => browse(tree.path)}>{tr("Refresh nodes")}</button>
    </div>
    <nav className="live-path" aria-label={tr("OPC UA node path")}>
      <button type="button" disabled={unavailable} onClick={() => browse([])} aria-current={!target ? "location" : undefined}>{tr("Objects")}</button>
      {tree.path.map((node, index) => <button type="button" key={`${index}-${node.node_id}`} aria-current={index === tree.path.length - 1 ? "location" : undefined} disabled={unavailable} onClick={() => browse(tree.path.slice(0, index + 1))}>{node.display_name}</button>)}
    </nav>
    <details>
      <summary>{tr("Open a node by ID")}</summary>
      <form className="live-record-form" onSubmit={e => {
        e.preventDefault();
        const value = nodeId.trim();
        if (value) browse([{ node_id: value, display_name: value }]);
      }}>
        <label>{tr("NodeId")}<input value={nodeId} onChange={e => setNodeId(e.target.value)} required maxLength={1024} placeholder="ns=2;s=CoupledTanks" /></label>
        <button className="ws-outlined" disabled={unavailable || !nodeId.trim()}>{tr("Browse children")}</button>
      </form>
    </details>
    {tree.nodes.length > 0 && <input aria-label={tr("Filter OPC UA nodes")} placeholder={tr("Filter by name or NodeId…")} value={filter} onChange={e => setFilter(e.target.value)} />}
    {!enabled && <p className="ws-notice">{tr("Browsing will resume when the server reconnects.")}</p>}
    {pending && <p className="live-hint" role="status">{tr(pending === "browse" ? "Browsing nodes…" : "Reading value…")}</p>}
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {nodes.length ? <div className="ws-table-scroll"><table>
      <thead><tr><th>{tr("Node")}</th><th>{tr("NodeId")}</th><th>{tr("Data type")}</th><th>{tr("Unit")}</th><th>{tr("Actions")}</th></tr></thead>
      <tbody>{nodes.map(node => {
        const selected = mappings.some(mapping => mapping.node_id === node.node_id);
        const variable = node.node_class === "Variable";
        return <tr key={node.node_id}>
          <th scope="row">{node.has_children ? <button className="ws-link live-node-link" type="button" disabled={unavailable} onClick={() => browse([...tree.path, node])}>{node.display_name} ›</button> : node.display_name}</th>
          <td><code>{node.node_id}</code></td>
          <td>{node.data_type || tr(`live.node.${node.node_class}`)}</td><td>{node.unit || "—"}</td>
          <td>{variable && <div className="ws-inline">
            <button className="ws-outlined" type="button" aria-label={tr("Read {0}", {0: node.display_name})} disabled={unavailable} onClick={() => read(node)}>{tr("Read value")}</button>
            <button className="ws-outlined live-toggle" type="button" aria-label={tr("Monitor {0}", {0: node.display_name})} aria-pressed={selected} disabled={unavailable || (!selected && mappings.length >= 64)} onClick={() => toggle(node)}>{tr("Monitor")}</button>
          </div>}</td>
        </tr>;
      })}</tbody>
    </table></div> : !pending && !error && enabled && <p className="live-hint">{tr(filter ? "No matching nodes." : "No child nodes.")}</p>}
    {reading && <div className="live-reading">
      <div className="ws-section-heading"><h3>{tr("Current reading")}</h3><button className="ws-outlined" type="button" onClick={() => setReading(null)}>{tr("Close")}</button></div>
      <strong>{reading.node.display_name}</strong>
      <dl className="live-connection-facts">
        <div><dt>{tr("Raw value")}</dt><dd>{readingValue(reading.sample.value)} {reading.node.unit}</dd></div>
        <div><dt>{tr("Quality")}</dt><dd><LiveQuality sample={reading.sample} /></dd></div>
        <div><dt>{tr("Source timestamp")}</dt><dd>{sampleDate(reading.sample.source_timestamp)}</dd></div>
        <div><dt>{tr("Server timestamp")}</dt><dd>{sampleDate(reading.sample.server_timestamp)}</dd></div>
      </dl>
    </div>}
  </section>;
}

export function LiveMappings({ mappings, catalog, busy, update, remove, start }: {
  mappings: LiveMappingDraft[];
  catalog: CatalogSignal[];
  busy: boolean;
  update: (mapping: LiveMappingDraft) => void;
  remove: (nodeId: string) => void;
  start: (name: string) => void;
}) {
  const [name, setName] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    if (name.trim()) start(name.trim());
  }
  return <form className="ws-panel live-panel" onSubmit={submit} aria-labelledby="live-mapping-title">
    <div className="ws-section-heading"><h2 id="live-mapping-title">{tr("Signal mappings")}</h2><span className="ws-muted">{tr("{0} selected", {0: mappings.length})}</span></div>
    {mappings.length ? <>
      <p className="ws-muted">{tr("Assign each node an existing signal or let L5 assign a stable identity. Mappings are saved with the recording.")}</p>
      <div className="live-mappings">{mappings.map(mapping => <fieldset key={mapping.node_id}>
        <legend>{mapping.node_id}</legend>
        <div className="ws-form-grid">
          <label>{tr("Display name")}<input value={mapping.display_name} onChange={e => update({ ...mapping, display_name: e.target.value })} maxLength={160} required /></label>
          <label>{tr("Engineering unit")}<input value={mapping.unit} onChange={e => update({ ...mapping, unit: e.target.value })} maxLength={160} /></label>
          <label>{tr("L5 signal")}<select value={mapping.signal_id || ""} onChange={e => {
            const signal = catalog.find(item => item.id === e.target.value);
            update({ ...mapping, signal_id: signal?.id, display_name: signal?.displayName || signal?.name || mapping.display_name, unit: signal?.unit || mapping.unit });
          }}>
            <option value="">{tr("Assign a live signal identity")}</option>
            {catalog.map(signal => <option key={signal.id} value={signal.id} disabled={mappings.some(other => other.node_id !== mapping.node_id && other.signal_id === signal.id)}>{signalLabel(signal)} · {signal.datasetName}</option>)}
          </select></label>
          <div className="live-mapping-actions"><span className="ws-muted">{mapping.data_type || tr("Unknown")}</span><button className="ws-outlined" type="button" onClick={() => remove(mapping.node_id)}>{tr("Remove")}</button></div>
        </div>
      </fieldset>)}</div>
      <div className="live-record-form">
        <label>{tr("Recording name")}<input value={name} onChange={e => setName(e.target.value)} required maxLength={160} placeholder={tr("e.g. Tank system startup")} /></label>
        <button className="ws-primary" disabled={busy || !name.trim()}>{tr("Start acquisition")}</button>
      </div>
    </> : <p className="live-hint">{tr("Choose Monitor on each variable you want to record.")}</p>}
  </form>;
}
