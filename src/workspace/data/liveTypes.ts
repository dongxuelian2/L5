export type LiveSecurityMode = "none" | "sign" | "sign_and_encrypt";

export type LiveConfig = {
  endpoint: string;
  security_mode: LiveSecurityMode;
  sampling_interval_ms: number;
  publishing_interval_ms: number;
  timeout_seconds: number;
  buffer_capacity: number;
  application_uri?: string;
  client_certificate?: string;
  client_private_key?: string;
  server_certificate?: string;
  username?: string;
  password?: string;
  private_key_password?: string;
};

export type LiveStatus = {
  connection_state: string;
  config: LiveConfig | null;
  last_error?: string | null;
  active_session_id?: string | null;
  buffered?: number;
  dropped?: number;
  last_notification_at?: string | null;
};

export type LiveNode = {
  node_id: string;
  display_name: string;
  node_class: string;
  data_type: string | null;
  unit: string | null;
  has_children: boolean;
  namespace_uri?: string | null;
};

export type LiveMappingDraft = {
  node_id: string;
  display_name: string;
  unit: string;
  data_type: string | null;
  signal_id?: string;
  namespace_uri?: string | null;
};

export type LiveMapping = LiveMappingDraft & { signal_id: string };

export type LiveSession = {
  id: string;
  workspace_id: string;
  name: string;
  state: "recording" | "completed" | "failed" | "interrupted";
  config: LiveConfig;
  mappings: LiveMapping[];
  started_at: string;
  stopped_at: string | null;
};

export type LiveReading = {
  node_id: string;
  signal_id?: string | null;
  value: unknown;
  timestamp: string;
  timestamp_origin: string;
  source_timestamp: string | null;
  server_timestamp: string | null;
  received_at: string;
  quality: string;
  status_name: string;
  status_code: number;
};

export type LiveSample = LiveReading & { id: number; signal_id: string };
export type LiveEvent = { id: number; kind: string; timestamp: string; detail: string; count?: number | null; node_id?: string; signal_id?: string };
export type LiveWindow = { samples: LiveSample[]; events: LiveEvent[]; latest?: LiveSample[] };
export type LiveRange = { start?: string; end?: string };
