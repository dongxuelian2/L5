import { animate, useReducedMotion } from "motion/react";
import { useEffect, useRef, type ReactNode } from "react";
type Tone = "mint" | "amber" | "coral" | "violet";

export function Panel({
  title,
  code,
  action,
  children,
  className = "",
  tone,
}: {
  title: string;
  code: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  tone?: Tone;
}) {
  return (
    <section className={`panel ${className} ${tone ? `panel-${tone}` : ""}`}>
      <div className="panel-heading">
        <div>
          <span className="section-code">{code}</span>
          <h2>{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Count({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const previous = useRef(value);
  const reduced = useReducedMotion();
  useEffect(() => {
    if (reduced) {
      if (ref.current) ref.current.textContent = String(value);
      previous.current = value;
      return;
    }
    const animation = animate(previous.current, value, {
      duration: 0.5,
      ease: "easeOut",
      onUpdate: (latest) => {
        if (ref.current)
          ref.current.textContent = Math.round(latest).toLocaleString("en");
      },
    });
    previous.current = value;
    return () => animation.stop();
  }, [value, reduced]);
  return <span ref={ref}>{value.toLocaleString("en")}</span>;
}

export function BlockBar({
  value,
  color = "mint",
  count = 20,
}: {
  value: number;
  color?: Tone;
  count?: number;
}) {
  return (
    <span className={`block-bar text-${color}`} aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className={i / count >= value ? "empty" : ""}>
          ▰
        </span>
      ))}
    </span>
  );
}
