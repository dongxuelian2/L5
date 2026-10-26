import { t } from "./index";

/** Localize known service errors at display time; retain unknown diagnostics. */
export function errorMessage(value: string) {
  const raw = value.replace(/^'(.+)'$/, "$1"); // Python KeyError representation.
  const exact = t(raw);
  if (exact !== raw) return exact;
  const patterns: [RegExp, string][] = [
    [/^Request failed \((\d+)\)\.$/, "Request failed ({0})."],
    [/^(.+) must be a finite number\.$/, "{0} must be a finite number."],
    [/^(.+) must be an integer\.$/, "{0} must be an integer."],
    [/^(.+) is outside its allowed range \((.+), (.+)\)\.$/, "{0} is outside its allowed range ({1}, {2})."],
    [/^(.+) needs two finite times in dataset seconds\.$/, "{0} needs two finite times in dataset seconds."],
    [/^(.+) must be inside the dataset time range\.$/, "{0} must be inside the dataset time range."],
    [/^(.+) needs a start and end time in seconds\.$/, "{0} needs a start and end time in seconds."],
    [/^(.+) must be inside the dataset time range, with start ≤ end\.$/, "{0} must be inside the dataset time range, with start ≤ end."],
    [/^(.+) contains no samples\.$/, "{0} contains no samples."],
    [/^An experiment is limited to (\d+) tasks\. Reduce study candidates or test runs\.$/, "An experiment is limited to {0} tasks. Reduce study candidates or test runs."],
    [/^Unable to read CSV: (.+)$/s, "Unable to read CSV: {0}"],
    [/^(.+): incompatible prepared TEP cache; run the preparation script again\.$/, "{0}: incompatible prepared TEP cache; run the preparation script again."],
  ];
  for (const [pattern, key] of patterns) {
    const match = raw.match(pattern);
    if (match) return t(key, Object.fromEntries(match.slice(1).map((part, i) => [i, part])));
  }
  return exact;
}
