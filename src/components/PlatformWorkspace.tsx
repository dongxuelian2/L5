import { RuntimeWorkbench } from "../workspace/RuntimeWorkbench";
export function PlatformWorkspace({ mode }: {
  mode: "investigate" | "learn";
  onModeChange: (mode: "investigate" | "learn") => void;
}) {
  return <RuntimeWorkbench initialTab={mode === "learn" ? "history" : "evidence"} />;
}
