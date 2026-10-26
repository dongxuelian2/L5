import { useEffect, useSyncExternalStore } from "react";
import messages from "./messages.json";
import common from "./common.json";
import catalog from "./catalog.json";
import serviceErrors from "./service-errors.json";
import "./language.css";

export type Locale = "zh-CN" | "en";
const storageKey = "l5.locale";
const listeners = new Set<() => void>();
export function preferredLocale(storage: Pick<Storage, "getItem"> | undefined, languages: readonly string[]): Locale {
  try { const saved = storage?.getItem(storageKey); if (saved === "zh-CN" || saved === "en") return saved; } catch { /* Private browsing may block storage. */ }
  return languages[0]?.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}
let locale: Locale | undefined;
export function getLocale(): Locale {
  if (!locale) {
    let storage: Storage | undefined;
    try { storage = window.localStorage; } catch { /* Keep an in-memory choice. */ }
    locale = preferredLocale(storage, typeof window === "undefined" ? [] : window.navigator.languages || [window.navigator.language]);
  }
  return locale;
}
function updateDocument() {
  if (typeof document === "undefined") return;
  document.documentElement.lang = getLocale();
  document.title = getLocale() === "zh-CN" ? "L5 · 工业分析与调查工作区" : "L5 · Industrial analysis & investigation";
}
export function setLocale(next: Locale) {
  locale = next;
  try { window.localStorage.setItem(storageKey, next); } catch { /* Switching still works without persistence. */ }
  updateDocument();
  listeners.forEach(listener => listener());
}
function subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }
export function useLocale() {
  const current = useSyncExternalStore(subscribe, getLocale, () => "en" as Locale);
  useEffect(updateDocument, [current]);
  return current;
}
/** Source keys refer only to application-owned copy. Never pass user data here. */
const copy: Record<string, readonly string[]> = { ...messages, ...common, ...catalog, ...serviceErrors };
const alternatives = new Map(Object.values(copy).flatMap(pair => pair.map(value => [value, pair] as const)));
const formats = Object.values(copy).flatMap(pair => pair.filter(value => /\{\d+\}/.test(value)).map(value => {
  const names: string[] = [];
  const parts = value.split(/(\{\d+\})/g).map(part => {
    if (/^\{\d+\}$/.test(part)) { names.push(part.slice(1, -1)); return "(.+?)"; }
    return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  });
  return { pattern: new RegExp("^" + parts.join("") + "$"), names, pair };
}));
export function t(key: string, params?: Record<string, unknown>): string;
export function t<T>(key: T, params?: Record<string, unknown>): T;
export function t(key: unknown, params?: Record<string, unknown>): unknown {
  if (typeof key !== "string") return key;
  const trimmed = key.trim();
  const pair = copy[key] || alternatives.get(key) || copy[trimmed] || alternatives.get(trimmed);
  let value = pair ? key.slice(0, key.length - key.trimStart().length) + pair[getLocale() === "zh-CN" ? 0 : 1] + key.slice(key.trimEnd().length) : key;
  if (!pair && !params) {
    for (const format of formats) {
      const match = trimmed.match(format.pattern);
      if (!match) continue;
      const values = Object.fromEntries(format.names.map((name, i) => [name, match[i + 1]]));
      value = format.pair[getLocale() === "zh-CN" ? 0 : 1].replace(/\{(\d+)\}/g, (_, name: string) => values[name]);
      break;
    }
  }
  return params ? value.replace(/\{(\w+)\}/g, (token, name: string) => Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : token) : value;
}
/** Runtime evidence uses fixed engine phrases, while saved tool payloads stay raw. */
export function runtimeText(value: string | undefined): string {
  if (!value) return "";
  for (const suffix of [" — not observed", " · extreme step", ": unreliable or missing evidence excluded"]) {
    if (value.endsWith(suffix)) return t("{0}" + suffix, {0: runtimeText(value.slice(0, -suffix.length))});
  }
  return t(value);
}
export function LanguageSwitch() {
  const current = useLocale();
  return <div className="language-switch" role="group" aria-label={t("Interface language")}>
    <button type="button" lang="zh-CN" aria-pressed={current === "zh-CN"} onClick={() => setLocale("zh-CN")}>中文</button>
    <span aria-hidden="true">/</span>
    <button type="button" lang="en" aria-pressed={current === "en"} onClick={() => setLocale("en")}>EN</button>
  </div>;
}
