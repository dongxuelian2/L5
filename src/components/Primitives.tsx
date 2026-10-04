import { animate, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Tone } from "../types";

export function Glyph({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span aria-hidden="true" className={`glyph ${className}`}>
      {children}
    </span>
  );
}

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
          ref.current.textContent = Math.round(latest).toLocaleString();
      },
    });
    previous.current = value;
    return () => animation.stop();
  }, [value, reduced]);
  return <span ref={ref}>{value.toLocaleString()}</span>;
}

export function ScrambleText({ text }: { text: string }) {
  const [display, setDisplay] = useState(text);
  const reduced = useReducedMotion();
  useEffect(() => {
    if (reduced) {
      setDisplay(text);
      return;
    }
    let tick = 0;
    const chars = "░▒▓01/\\·";
    const timer = window.setInterval(() => {
      tick++;
      setDisplay(
        text
          .split("")
          .map((c, i) =>
            c === " " || i < tick * 2 ? c : chars[(i + tick) % chars.length],
          )
          .join(""),
      );
      if (tick * 2 >= text.length) clearInterval(timer);
    }, 28);
    return () => clearInterval(timer);
  }, [text, reduced]);
  return (
    <span aria-label={text}>
      <span aria-hidden="true">{display}</span>
    </span>
  );
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

export function StatusDot({
  tone = "mint",
  pulse = false,
}: {
  tone?: Tone;
  pulse?: boolean;
}) {
  return (
    <span
      aria-hidden="true"
      className={`status-dot bg-${tone} ${pulse ? "pulse" : ""}`}
    />
  );
}

export function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay }}
    >
      {children}
    </motion.div>
  );
}
