import labels from "../../l5/labels.json";

export type Message = [text: string, params?: Record<string, unknown>];
const copy: Readonly<Record<string, string>> = labels;

export function t(value: string, params?: Record<string, unknown>): string;
export function t<T>(value: T, params?: Record<string, unknown>): T;
export function t(value: unknown, params?: Record<string, unknown>): unknown {
  if (typeof value !== "string") return value;
  const text = Object.hasOwn(copy, value) ? copy[value] : value;
  return params ? text.replace(/\{(\w+)\}/g, (token, name: string) =>
    Object.hasOwn(params, name) ? String(params[name]) : token) : text;
}

export function runtimeText(value?: string): string {
  return t(value ?? "");
}

export function errorMessage(value: string): string {
  return value.replace(/^'(.+)'$/, "$1");
}
