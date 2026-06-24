// RTL / bidi-safe formatters. All functions are pure so they can be used
// from server or client components.

export const OWNER_TZ = "Africa/Cairo";

const EM_DASH = "—";

// Unicode bidi isolation: First-Strong Isolate (U+2068) ... Pop Directional
// Isolate (U+2069). Wrapping mixed Arabic / Latin / digit runs in these keeps
// them from reordering the surrounding RTL text.
const FSI = "⁨";
const PDI = "⁩";

/** Wrap a value in first-strong bidi isolation so it renders predictably
 *  inside RTL text. Use for numbers, percentages, money, URLs, etc. */
export function bidiIsolate(value: string | number): string {
  return `${FSI}${value}${PDI}`;
}

const absoluteFmt = new Intl.DateTimeFormat("ar", {
  timeZone: OWNER_TZ,
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/** Localized absolute date-time in the owner's timezone. */
export function formatAbsolute(iso: string | null): string {
  if (!iso) return EM_DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return EM_DASH;
  return bidiIsolate(absoluteFmt.format(d));
}

const relativeFmt = new Intl.RelativeTimeFormat("ar", { numeric: "auto" });

const DIVISIONS: { amount: number; unit: Intl.RelativeTimeFormatUnit }[] = [
  { amount: 60, unit: "second" },
  { amount: 60, unit: "minute" },
  { amount: 24, unit: "hour" },
  { amount: 7, unit: "day" },
  { amount: 4.34524, unit: "week" },
  { amount: 12, unit: "month" },
  { amount: Number.POSITIVE_INFINITY, unit: "year" },
];

/** Arabic relative age, e.g. "منذ ٥ دقائق". */
export function formatRelative(iso: string | null): string {
  if (!iso) return EM_DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return EM_DASH;

  let duration = (d.getTime() - Date.now()) / 1000; // seconds, negative for past
  for (const division of DIVISIONS) {
    if (Math.abs(duration) < division.amount) {
      return relativeFmt.format(Math.round(duration), division.unit);
    }
    duration /= division.amount;
  }
  return EM_DASH;
}

const numberFmt = new Intl.NumberFormat("ar-EG");

/** Localized number, bidi-isolated. Null → "غير محدد". */
export function formatNumber(n: number | null): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "غير محدد";
  return bidiIsolate(numberFmt.format(n));
}

/**
 * Budget range rendered bidi-safe. Handles single-bound and missing values.
 * Null/empty range → "غير محدد".
 */
export function formatBudget(
  min: number | null,
  max: number | null,
  currency: string | null
): string {
  const cur = currency ? ` ${currency}` : "";
  const fmt = (v: number) => numberFmt.format(v);

  let range: string;
  if (min != null && max != null) {
    range = min === max ? fmt(min) : `${fmt(min)} - ${fmt(max)}`;
  } else if (min != null) {
    range = fmt(min);
  } else if (max != null) {
    range = fmt(max);
  } else {
    return "غير محدد";
  }

  return bidiIsolate(`${range}${cur}`);
}

/** Client hiring rate. Null → "لم يحسب بعد"; else "%<rate>" bidi-isolated. */
export function formatHiringRate(rate: number | null): string {
  if (rate === null || rate === undefined || Number.isNaN(rate)) {
    return "لم يحسب بعد";
  }
  return bidiIsolate(`%${numberFmt.format(rate)}`);
}
