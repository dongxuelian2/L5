import { api, message } from "./api";
import type { Series } from "./types";

export type SignalSeries = {
  times: number[];
  values: (number | null)[];
  segmentIds?: number[];
  sourceRows: number;
  displayRows: number;
};

// An immutable dataset and time window own the data. Checkbox visibility does not.
// Each signal keeps its own timestamps: separately downsampled responses can differ.
export class SeriesCache {
  readonly signals = new Map<string, SignalSeries>();
  readonly errors = new Map<string, string>();
  private pending = new Set<string>();
  private listeners = new Set<() => void>();
  private version = 0;

  constructor(readonly datasetId: string, readonly range?: [number, number]) {}

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  snapshot = () => this.version;
  get unused() { return !this.listeners.size && !this.pending.size; }

  private notify() {
    this.version++;
    this.listeners.forEach(listener => listener());
  }

  async load(names: string[], retry = false) {
    const missing = [...new Set(names)].filter(name => !this.signals.has(name) && !this.pending.has(name) && (retry || !this.errors.has(name)));
    if (!missing.length) return;
    missing.forEach(name => { this.pending.add(name); this.errors.delete(name); });
    this.notify();
    const params = new URLSearchParams();
    missing.forEach(name => params.append("signal", name));
    if (this.range) { params.set("start", String(this.range[0])); params.set("end", String(this.range[1])); }
    try {
      const data = await api<Series>(`/datasets/${this.datasetId}/series?${params}`);
      for (const name of missing) {
        if (!Object.hasOwn(data.values, name)) throw new Error(`No measurements returned for ${name}.`);
        this.signals.set(name, { times: data.times, values: data.values[name], segmentIds: data.segmentIds?.[name], sourceRows: data.sourceRows, displayRows: data.displayRows });
      }
    } catch (error) {
      missing.forEach(name => this.errors.set(name, message(error)));
    } finally {
      missing.forEach(name => this.pending.delete(name));
      this.notify();
    }
  }
}

const windows = new Map<string, SeriesCache>();
export function cachedSeries(datasetId: string, range?: [number, number]) {
  const key = JSON.stringify([datasetId, range ?? null]);
  let entry = windows.get(key);
  if (!entry) {
    // Keep a few recently visited windows without retaining every dataset forever.
    for (const [oldKey, old] of windows) {
      if (windows.size < 8) break;
      if (old.unused) windows.delete(oldKey);
    }
    entry = new SeriesCache(datasetId, range);
  }
  windows.delete(key);
  windows.set(key, entry);
  return entry;
}
