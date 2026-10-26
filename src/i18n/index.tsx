import { useEffect, useSyncExternalStore } from "react";
import messages from "./messages.json";
import common from "./common.json";
import catalog from "./catalog.json";
import serviceErrors from "./service-errors.json";
import "./language.css";

export type Locale = "zh-CN" | "en";
export type Message = [key: string, params?: Record<string, unknown>];
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
// Source keys win. Only unambiguous English labels may stand in for a source key;
// Chinese translations and rendered messages are never parsed back into keys.
const english = new Map<string, readonly string[] | null>();
for (const pair of Object.values(copy)) {
  if (!english.has(pair[1])) english.set(pair[1], pair);
  else if (english.get(pair[1])?.[0] !== pair[0]) english.set(pair[1], null);
}
export function t(key: string, params?: Record<string, unknown>): string;
export function t<T>(key: T, params?: Record<string, unknown>): T;
export function t(key: unknown, params?: Record<string, unknown>): unknown {
  if (typeof key !== "string") return key;
  const trimmed = key.trim();
  const pair = copy[key] || copy[trimmed] || english.get(trimmed);
  const value = pair ? key.slice(0, key.length - key.trimStart().length) + pair[getLocale() === "zh-CN" ? 0 : 1] + key.slice(key.trimEnd().length) : key;
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
