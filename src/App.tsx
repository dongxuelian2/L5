import { lazy, Suspense, useEffect, useRef, useState } from "react";
import WorkspaceApp from "./workspace/WorkspaceApp";

const ExamplesApp = lazy(() => import("./ExamplesApp"));

export default function App() {
  const [hash, setHash] = useState(window.location.hash);
  const previousRoute = useRef(window.location.hash.split("?")[0]);
  useEffect(() => {
    const update = () => {
      const next = window.location.hash, route = next.split("?")[0];
      setHash(next);
      if (route !== previousRoute.current) window.scrollTo(0, 0);
      previousRoute.current = route;
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  const [route, search = ""] = hash.replace(/^#\/?/, "").split("?");
  const path = route.split("/").filter(Boolean);
  if (path[0] === "examples") return <><div className="ws-example-banner"><a href="#/">← L5 Workspaces</a><span>TRIPLENS / PROCESS MODELS & EXAMPLES</span></div><Suspense fallback={<p className="ws-main">Loading TripLens examples…</p>}><ExamplesApp /></Suspense></>;
  return <WorkspaceApp path={path} search={search} />;
}
