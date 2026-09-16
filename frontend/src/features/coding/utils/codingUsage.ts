import type { CodingDiagnostics, CodingRun } from "../../../api/coding";

/** Normalized token usage for one run or a whole session. */
export interface TokenUsageSummary {
  input?: number;
  output?: number;
  total?: number;
  cached?: number;
  /** Context-window usage snapshot (max observed; never summed). */
  used?: number;
  size?: number;
  costAmount?: number;
  costCurrency?: string | null;
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function hasAny(summary: TokenUsageSummary): boolean {
  return (
    summary.input !== undefined ||
    summary.output !== undefined ||
    summary.total !== undefined ||
    summary.cached !== undefined ||
    summary.used !== undefined ||
    summary.size !== undefined ||
    summary.costAmount !== undefined
  );
}

function fromDiagnostics(diag: CodingDiagnostics | null | undefined): TokenUsageSummary | null {
  if (!diag) return null;
  const cumulative = diag.usage_cumulative ?? null;
  const source = cumulative ?? diag.usage ?? null;
  if (!source) return null;

  const summary: TokenUsageSummary = {};
  const input = finiteNumber(source.input);
  const output = finiteNumber(source.output);
  const total = finiteNumber(source.total);
  const cached = finiteNumber(source.cached);
  if (input !== undefined) summary.input = input;
  if (output !== undefined) summary.output = output;
  if (total !== undefined) summary.total = total;
  if (cached !== undefined) summary.cached = cached;

  if (cumulative) {
    const used = finiteNumber(cumulative.used_max);
    const size = finiteNumber(cumulative.size_max);
    if (used !== undefined && used > 0) summary.used = used;
    if (size !== undefined && size > 0) summary.size = size;
  } else {
    const used = finiteNumber(diag.usage?.used);
    const size = finiteNumber(diag.usage?.size);
    if (used !== undefined && used > 0) summary.used = used;
    if (size !== undefined && size > 0) summary.size = size;
  }

  const costAmount = finiteNumber(source.cost?.amount);
  const costCurrency = source.cost?.currency ?? null;
  if (costAmount !== undefined && (costAmount > 0 || costCurrency)) {
    summary.costAmount = costAmount;
  }
  if (costCurrency) summary.costCurrency = costCurrency;

  return hasAny(summary) ? summary : null;
}

/**
 * Token usage for a single run. Prefers the run-wide accumulation over every
 * worker attempt; falls back to the legacy last-attempt block for runs that
 * predate the accumulation.
 */
export function runUsageSummary(run: CodingRun | null | undefined): TokenUsageSummary | null {
  return fromDiagnostics(run?.diagnostics);
}

/** Whether the given run carries a multi-attempt accumulation block. */
export function hasCumulativeUsage(run: CodingRun | null | undefined): boolean {
  return !!run?.diagnostics?.usage_cumulative;
}

/** Add two summaries: token counts and cost sum, context-window values maxed. */
function mergeSummary(into: TokenUsageSummary, add: TokenUsageSummary): void {
  for (const key of ["input", "output", "total", "cached"] as const) {
    const value = add[key];
    if (value !== undefined) into[key] = (into[key] ?? 0) + value;
  }
  for (const key of ["used", "size"] as const) {
    const value = add[key];
    if (value !== undefined) into[key] = Math.max(into[key] ?? 0, value);
  }
  if (add.costAmount !== undefined) {
    into.costAmount = (into.costAmount ?? 0) + add.costAmount;
  }
  if (add.costCurrency) into.costCurrency = add.costCurrency;
}

/** Session-wide accumulation across every run of the session. */
export function sessionUsageSummary(
  runs: (CodingRun | null | undefined)[],
): TokenUsageSummary | null {
  const total: TokenUsageSummary = {};
  let found = false;
  for (const run of runs) {
    const summary = runUsageSummary(run);
    if (summary) {
      mergeSummary(total, summary);
      found = true;
    }
  }
  return found ? total : null;
}

/**
 * Human-readable token breakdown, e.g.
 * "入力 1.2k / キャッシュ読取 300 / 出力 40 / 合計 1.5k".
 * Cost is appended by the caller so the run and header can style it.
 */
export function formatTokenBreakdown(summary: TokenUsageSummary): string {
  const parts: string[] = [];
  if (summary.input !== undefined) parts.push(`入力 ${formatTokens(summary.input)}`);
  if (summary.cached !== undefined) parts.push(`キャッシュ読取 ${formatTokens(summary.cached)}`);
  if (summary.output !== undefined) parts.push(`出力 ${formatTokens(summary.output)}`);
  if (summary.total !== undefined) parts.push(`合計 ${formatTokens(summary.total)}`);
  if (summary.used !== undefined) {
    parts.push(
      summary.size !== undefined
        ? `使用 ${formatTokens(summary.used)} / ${formatTokens(summary.size)}`
        : `使用 ${formatTokens(summary.used)}`,
    );
  }
  return parts.join(" / ");
}

/** Compact token count, e.g. 1234 -> "1.2k", 1234567 -> "1.23M". */export function formatTokens(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "0";
  if (value < 1000) return String(Math.round(value));
  if (value < 1_000_000) {
    const k = value / 1000;
    return `${k < 10 ? k.toFixed(1) : Math.round(k)}k`;
  }
  const m = value / 1_000_000;
  return `${m < 10 ? m.toFixed(2) : m.toFixed(1)}M`;
}

/** Billed cost, e.g. (0.03, "USD") -> "0.03 USD". */
export function formatCost(amount: number, currency?: string | null): string {
  // Trim binary-float artifacts from summed costs (0.1 + 0.2).
  const rounded = Number(amount.toFixed(6));
  return `${rounded}${currency ? ` ${currency}` : ""}`;
}
