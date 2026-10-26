import { useLocale } from "../i18n";
import { RuntimeWorkbench } from "../workspace/RuntimeWorkbench";
export function PlatformWorkspace({ mode }: {
  mode: "investigate" | "learn";
  onModeChange: (mode: "investigate" | "learn") => void;
}) {
  useLocale();
  return <RuntimeWorkbench initialTab={mode === "learn" ? "history" : "evidence"} />;
}
