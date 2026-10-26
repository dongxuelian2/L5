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
    [/^Incompatible signal spaces: (.+) \/ (.+); an explicit verified adapter is required\.$/, "Incompatible signal spaces: {0} / {1}; an explicit verified adapter is required."],
    [/^Only applicable parameters are allowed for (.+): (.+)\.$/, "Only applicable parameters are allowed for {0}: {1}."],
    [/^At most (\d+) local runs may be active\. Wait for a batch to finish\.$/, "At most {0} local runs may be active. Wait for a batch to finish."],
    [/^Unknown signal key: (.+)\. Choose an explicitly selected source or earlier derived signal\.$/, "Unknown signal key: {0}. Choose an explicitly selected source or earlier derived signal."],
    [/^(.+) needs (\d+) argument\(s\)\.$/, "{0} needs {1} argument(s)."],
    [/^(.+) requires a dimensionless argument\.$/, "{0} requires a dimensionless argument."],
    [/^(.+)必须是文本，最多 (\d+) 个字符。$/, "{0}必须是文本，最多 {1} 个字符。"],
    [/^This partition requires at least (\d+) observations\.$/, "This partition requires at least {0} observations."],
    [/^Expected (\d+) variables; received (\d+)\.$/, "Expected {0} variables; received {1}."],
    [/^This model does not support (.+)\.$/, "This model does not support {0}."],
    [/^(.+): missing or incomplete official source; expected (\d+) bytes\.$/, "{0}: missing or incomplete official source; expected {1} bytes."],
    [/^(.+): original file checksum differs from Harvard Dataverse V1\.$/, "{0}: original file checksum differs from Harvard Dataverse V1."],
    [/^(.+): source SHA-256 differs from the pinned reference\.$/, "{0}: source SHA-256 differs from the pinned reference."],
    [/^(.+): invalid fault\/run identity, onset or sampling protocol in prepared cache\.$/, "{0}: invalid fault/run identity, onset or sampling protocol in prepared cache."],
    [/^(.+): prepared data missing or corrupt; prepare it again from the verified source\.$/, "{0}: prepared data missing or corrupt; prepare it again from the verified source."],
    [/^(.+): invalid selected run schema, measurements or sample indices\.$/, "{0}: invalid selected run schema, measurements or sample indices."],
    [/^(.+): prepared provenance does not match the pinned official source\.$/, "{0}: prepared provenance does not match the pinned official source."],
    [/^Saved study (.+) differs from its fixed protocol\.$/, "Saved study {0} differs from its fixed protocol."],
    [/^No explicit conversion from (.+) to (.+)\. Custom units can only be preserved\.$/, "No explicit conversion from {0} to {1}. Custom units can only be preserved."],
    [/^(.+) must be between (.+) and (.+) (.*?)\.$/, "{0} must be between {1} and {2} {3}."],
  ];
  for (const [pattern, key] of patterns) {
    const match = raw.match(pattern);
    if (match) {
      const parts = match.slice(1);
      if (key === "{0}必须是文本，最多 {1} 个字符。") parts[0] = t(parts[0]);
      return t(key, Object.fromEntries(parts.map((part, i) => [i, part])));
    }
  }
  return exact;
}
