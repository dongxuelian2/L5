import { useEffect, useRef, useState } from "react";
import WorkspaceApp from "./workspace/WorkspaceApp";

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
  return <WorkspaceApp key={path[0] === "workspaces" ? path[1] : path[0]} path={path} search={search} />;
}
