import { useEffect, useId, useRef, useState } from "react";
import { motion } from "motion/react";
import { Modal } from "./Overlays";

export interface WorkstationCommand {
  id: string;
  title: string;
  group: string;
  hint: string;
  keywords?: string;
  disabled?: boolean;
  run: () => void;
}

export function CommandPalette({
  commands,
  onClose,
}: {
  commands: WorkstationCommand[];
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const terms = query.toLowerCase().trim().split(/\s+/);
  const matches = commands.filter((command) =>
    terms.every((term) =>
      `${command.title} ${command.group} ${command.keywords ?? ""}`
        .toLowerCase()
        .includes(term),
    ),
  );
  const active = matches[Math.min(selected, matches.length - 1)];
  useEffect(() => {
    const frame = requestAnimationFrame(() => input.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, []);
  useEffect(() => {
    if (active)
      document
        .getElementById(`${listId}-${active.id}`)
        ?.scrollIntoView({ block: "nearest" });
  }, [active, listId]);
  const execute = (command: WorkstationCommand) => {
    if (!command.disabled) command.run();
  };
  return (
    <Modal
      title="Where do you want to go?"
      eyebrow="COMMAND LINE / QUICK NAVIGATION"
      onClose={onClose}
    >
      <div className="command-search">
        <span aria-hidden="true">❯</span>
        <input
          ref={input}
          role="combobox"
          aria-label="Search commands"
          aria-autocomplete="list"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={active ? `${listId}-${active.id}` : undefined}
          placeholder="Search signals, actions, or chapters…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setSelected(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              if (matches.length)
                setSelected(
                  (index) =>
                    (index +
                      (event.key === "ArrowDown" ? 1 : -1) +
                      matches.length) %
                    matches.length,
                );
            }
            if (event.key === "Enter") {
              event.preventDefault();
              if (active) execute(active);
            }
          }}
        />
        <kbd>↵</kbd>
      </div>
      <div
        id={listId}
        className="command-results"
        role="listbox"
        aria-label="Available commands"
      >
        {matches.map((command, index) => (
          <div
            role="option"
            aria-selected={active?.id === command.id}
            aria-disabled={command.disabled || undefined}
            id={`${listId}-${command.id}`}
            key={command.id}
            className={`command-option ${active?.id === command.id ? "selected" : ""} ${command.disabled ? "disabled" : ""}`}
            onMouseMove={() => setSelected(index)}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => execute(command)}
          >
            <span className="command-group">{command.group}</span>
            <span className="command-title">{command.title}</span>
            <span className="command-hint">
              {command.disabled ? "awaiting signals" : command.hint}
            </span>
            {active?.id === command.id && (
              <motion.span
                className="command-selector"
                layoutId="command-selected"
                aria-hidden="true"
              >
                ↵
              </motion.span>
            )}
          </div>
        ))}
        {!matches.length && (
          <div className="command-empty">
            <span aria-hidden="true">∅</span>
            <strong>No matching commands.</strong>
            <p>Try “pressure”, “replay”, “bypass”, or a signal tag.</p>
          </div>
        )}
      </div>
      <div className="command-footer">
        <span>
          <kbd>↑</kbd>
          <kbd>↓</kbd> navigate
        </span>
        <span>
          <kbd>↵</kbd> select
        </span>
        <span>
          <kbd>ESC</kbd> close
        </span>
        <span>{matches.length} commands</span>
      </div>
    </Modal>
  );
}
