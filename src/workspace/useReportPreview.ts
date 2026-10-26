import { useEffect, useRef, useState } from "react";
import { message } from "./api";

/** Shared HTML preview lifecycle; each report keeps its own content and exports. */
export function useReportPreview(url: string, source: unknown, failureMessage: string) {
  const [html, setHtml] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false), [ready, setReady] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null), generation = useRef(0);
  useEffect(() => { generation.current++; setHtml(""); setError(""); setReady(false); setBusy(false); }, [url, source]);
  useEffect(() => () => { generation.current++; }, []);
  async function generate() {
    const request = ++generation.current;
    setBusy(true); setError(""); setReady(false);
    try {
      const response = await fetch(url);
      if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) throw new Error(failureMessage);
      const content = await response.text();
      if (request === generation.current) setHtml(content);
    } catch (e) { if (request === generation.current) setError(message(e)); }
    finally { if (request === generation.current) setBusy(false); }
  }
  function print() { frame.current?.contentWindow?.focus(); frame.current?.contentWindow?.print(); }
  return { html, error, busy, ready, setReady, frame, generate, print };
}
