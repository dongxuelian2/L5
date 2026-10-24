import { useEffect, useRef, useState } from "react";
import type { Analysis } from "../lib/platform";
import { api, message } from "./api";

export type ObservationWindow = { asOf: number; windowStart: number };
export type ObservationContext = ObservationWindow & { sessionId: string };
export type Observation = Analysis & { asOf: number; observedThrough: number; windowStart: number; samples: number };
type ResolvedObservation = { context: ObservationContext; analysis: Observation };

export function observationKey(context: ObservationContext): string {
  return JSON.stringify([context.sessionId, context.windowStart, context.asOf]);
}

/** Keep the rendered plots while only exposing conclusions for the selected window. */
export function useObservation(context: ObservationContext | null) {
  const key = context ? observationKey(context) : null;
  const activeKey = useRef(key);
  activeKey.current = key;
  const cache = useRef(new Map<string, ResolvedObservation>());
  const retained = useRef<ResolvedObservation | null>(null);
  const request = useRef(0);
  const [completed, setCompleted] = useState<ResolvedObservation | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const current = key ? cache.current.get(key) ?? (completed && observationKey(completed.context) === key ? completed : null) : null;
  if (current) retained.current = current;

  useEffect(() => {
    if (!context || !key || cache.current.has(key)) return;
    const selected = { ...context }, controller = new AbortController(), version = ++request.current;
    const isCurrent = () => !controller.signal.aborted && version === request.current && activeKey.current === key;
    const timer = setTimeout(() => {
      api<Observation>(`/simulations/${selected.sessionId}/analysis`, { asOf: selected.asOf, windowStart: selected.windowStart }, "POST", controller.signal)
        .then(analysis => {
          if (!isCurrent()) return;
          const result = { context: selected, analysis };
          cache.current.set(key, result);
          while (cache.current.size > 128) cache.current.delete(cache.current.keys().next().value!);
          setCompleted(result);
          setFailure(null);
        })
        .catch(error => { if (isCurrent()) setFailure({ key, message: message(error) }); });
    }, 180);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [key]);

  const error = failure?.key === key ? failure.message : "";
  return {
    key,
    analysis: current?.analysis ?? null,
    retained: retained.current,
    pending: Boolean(context && !current && !error),
    error,
  };
}
