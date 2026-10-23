import { lazy, Suspense, useEffect, useState } from "react";
import WorkspaceApp from "./workspace/WorkspaceApp";

const ExamplesApp = lazy(() => import("./ExamplesApp"));

export default function App() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const update = () => { setHash(window.location.hash); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  const path = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (path[0] === "examples") return <><div className="ws-example-banner"><a href="#/">← L5 Workspaces</a><span>TRIPLENS / PROCESS MODELS & EXAMPLES</span></div><Suspense fallback={<p className="ws-main">Loading TripLens examples…</p>}><ExamplesApp /></Suspense></>;
  return <WorkspaceApp path={path} />;
}
