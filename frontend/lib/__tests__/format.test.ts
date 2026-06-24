/// <reference types="vitest/globals" />
import {
  OWNER_TZ,
  bidiIsolate,
  formatAbsolute,
  formatRelative,
  formatNumber,
  formatBudget,
  formatHiringRate,
} from "@/lib/format";

const FSI = "⁨"; // First-Strong Isolate (source uses U+2068)
const PDI = "⁩"; // Pop Directional Isolate

describe("bidiIsolate", () => {
  it("wraps a string between FSI and PDI", () => {
    const r = bidiIsolate("abc");
    expect(r.startsWith(FSI)).toBe(true);
    expect(r.endsWith(PDI)).toBe(true);
    expect(r).toContain("abc");
    expect(r).toBe(`${FSI}abc${PDI}`);
  });

  it("wraps a number value", () => {
    const r = bidiIsolate(123);
    expect(r).toBe(`${FSI}123${PDI}`);
    expect(r).toContain("123");
  });

  it("handles empty string input", () => {
    expect(bidiIsolate("")).toBe(`${FSI}${PDI}`);
  });
});

describe("formatHiringRate", () => {
  it("null → 'لم يحسب بعد'", () => {
    expect(formatHiringRate(null)).toBe("لم يحسب بعد");
  });

  it("a real 0 is NOT 'لم يحسب بعد' — shows a real zero", () => {
    const r = formatHiringRate(0);
    expect(r).not.toBe("لم يحسب بعد");
    expect(r).toContain("%");
    // Arabic-Indic zero is ٠ (U+0660)
    expect(r).toContain("٠");
  });

  it("0.0 is distinct from null", () => {
    expect(formatHiringRate(0)).not.toBe(formatHiringRate(null));
  });

  it("80 → contains the digits and a %", () => {
    const r = formatHiringRate(80);
    expect(r).toContain("%");
    // 80 in Arabic-Indic digits ٨٠; assert the latin string maps
    expect(r).toBe(`${FSI}%${new Intl.NumberFormat("ar-EG").format(80)}${PDI}`);
  });
});

describe("formatRelative", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-24T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("null → em dash", () => {
    expect(formatRelative(null)).toBe("—");
  });

  it("invalid date → em dash", () => {
    expect(formatRelative("not-a-date")).toBe("—");
  });

  it("~5 minutes ago → non-empty Arabic string with a digit", () => {
    const r = formatRelative("2026-06-24T11:55:00Z");
    expect(r.length).toBeGreaterThan(0);
    expect(r).not.toBe("—");
    // ICU may emit Western or Arabic-Indic digits; assert either.
    expect(/[0-9٠-٩]/.test(r)).toBe(true);
  });

  it("~3 hours ago and ~2 days ago differ and are non-empty", () => {
    const hours = formatRelative("2026-06-24T09:00:00Z");
    const days = formatRelative("2026-06-22T12:00:00Z");
    expect(hours).not.toBe("—");
    expect(days).not.toBe("—");
    expect(hours).not.toBe(days);
  });

  it("a FUTURE timestamp is handled without throwing", () => {
    expect(() => formatRelative("2026-06-25T12:00:00Z")).not.toThrow();
    const r = formatRelative("2026-06-25T12:00:00Z");
    expect(r).not.toBe("—");
  });
});

describe("formatAbsolute", () => {
  it("null → em dash", () => {
    expect(formatAbsolute(null)).toBe("—");
  });

  it("invalid date → em dash", () => {
    expect(formatAbsolute("garbage")).toBe("—");
  });

  it("renders a non-empty string for a known ISO", () => {
    const r = formatAbsolute("2026-06-24T12:00:00Z");
    expect(r.length).toBeGreaterThan(0);
    expect(r).not.toBe("—");
  });

  it("is bidi-isolated", () => {
    const r = formatAbsolute("2026-06-24T12:00:00Z");
    expect(r.startsWith(FSI)).toBe(true);
    expect(r.endsWith(PDI)).toBe(true);
  });

  it("renders in OWNER_TZ (Africa/Cairo)", () => {
    expect(OWNER_TZ).toBe("Africa/Cairo");
    const iso = "2026-06-24T12:00:00Z";
    const expected = new Intl.DateTimeFormat("ar", {
      timeZone: OWNER_TZ,
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
    expect(r_unwrap(formatAbsolute(iso))).toBe(expected);

    // Summer in Cairo is UTC+3 (DST). 12:00 UTC → 15:00 local. Assert the
    // hour reflects the offset rather than UTC by comparing to a UTC render.
    const utcRender = new Intl.DateTimeFormat("ar", {
      timeZone: "UTC",
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
    expect(expected).not.toBe(utcRender);
  });
});

function r_unwrap(s: string): string {
  return s.replace(/^⁨/, "").replace(/⁩$/, "");
}

describe("formatNumber", () => {
  it("null → 'غير محدد' (source's unset string)", () => {
    expect(formatNumber(null)).toBe("غير محدد");
  });

  it("NaN → 'غير محدد'", () => {
    expect(formatNumber(Number.NaN)).toBe("غير محدد");
  });

  it("a number contains its digits and is bidi-isolated", () => {
    const r = formatNumber(1234);
    expect(r.startsWith(FSI)).toBe(true);
    expect(r.endsWith(PDI)).toBe(true);
    expect(r_unwrap(r)).toBe(new Intl.NumberFormat("ar-EG").format(1234));
  });

  it("zero is rendered (not treated as unset)", () => {
    const r = formatNumber(0);
    expect(r).not.toBe("غير محدد");
    expect(r).toContain("٠");
  });
});

describe("formatBudget", () => {
  const ar = (n: number) => new Intl.NumberFormat("ar-EG").format(n);

  it("min+max present → contains both and the currency", () => {
    const r = formatBudget(100, 500, "USD");
    expect(r).toContain(ar(100));
    expect(r).toContain(ar(500));
    expect(r).toContain("USD");
    expect(r.startsWith(FSI)).toBe(true);
    expect(r.endsWith(PDI)).toBe(true);
  });

  it("min === max → single value, not a range", () => {
    const r = formatBudget(200, 200, "USD");
    expect(r_unwrap(r)).toBe(`${ar(200)} USD`);
    expect(r).not.toContain("-");
  });

  it("only min present → graceful single bound", () => {
    const r = formatBudget(100, null, "USD");
    expect(r_unwrap(r)).toBe(`${ar(100)} USD`);
  });

  it("only max present → graceful single bound", () => {
    const r = formatBudget(null, 500, "USD");
    expect(r_unwrap(r)).toBe(`${ar(500)} USD`);
  });

  it("both null → 'غير محدد'", () => {
    expect(formatBudget(null, null, "USD")).toBe("غير محدد");
    expect(formatBudget(null, null, null)).toBe("غير محدد");
  });

  it("no currency → no trailing currency", () => {
    const r = formatBudget(100, 500, null);
    expect(r_unwrap(r)).toBe(`${ar(100)} - ${ar(500)}`);
  });
});
