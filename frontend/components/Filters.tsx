"use client";

import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";

import {
  type ProjectFilters,
  type SortField,
  type SortOrder,
  type UseProjectsResult,
} from "@/lib/useProjects";
import { useStatuses } from "@/lib/useStatuses";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const ANY = "any";

/** Parse a number input into a filter value (empty → undefined). */
function numOrUndef(raw: string): number | undefined {
  if (raw.trim() === "") return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

function NumberField({
  id,
  label,
  value,
  min,
  max,
  placeholder,
  onCommit,
}: {
  id: string;
  label: string;
  value: number | undefined;
  min?: number;
  max?: number;
  placeholder?: string;
  onCommit: (v: number | undefined) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        placeholder={placeholder}
        defaultValue={value ?? ""}
        // Commit on blur / Enter so we don't push to the URL on every keystroke.
        key={`${id}-${value ?? ""}`}
        onBlur={(e) => onCommit(numOrUndef(e.target.value))}
        onKeyDown={(e) => {
          if (e.key === "Enter") onCommit(numOrUndef(e.currentTarget.value));
        }}
      />
    </div>
  );
}

export function Filters({ controller }: { controller: UseProjectsResult }) {
  const { params, filtersActive, setFilters, setSort, clearFilters } =
    controller;
  const { data: statusOptions } = useStatuses();

  // Debounced keyword search (~300ms) decoupled from the committed URL value.
  const [qDraft, setQDraft] = useState(params.q ?? "");
  const lastPushed = useRef(params.q ?? "");

  // Keep the draft in sync when the URL value changes externally
  // (e.g. clear filters, back/forward navigation).
  useEffect(() => {
    const current = params.q ?? "";
    if (current !== lastPushed.current) {
      lastPushed.current = current;
      setQDraft(current);
    }
  }, [params.q]);

  useEffect(() => {
    const trimmed = qDraft.trim();
    const next = trimmed === "" ? undefined : trimmed;
    const current = lastPushed.current === "" ? undefined : lastPushed.current;
    if (next === current) return;

    const t = setTimeout(() => {
      lastPushed.current = trimmed;
      setFilters({ q: next });
    }, 300);
    return () => clearTimeout(t);
  }, [qDraft, setFilters]);

  const patch = (p: Partial<ProjectFilters>) => setFilters(p);

  return (
    <section
      aria-label="عوامل التصفية"
      className="flex flex-col gap-4 rounded-lg border bg-card p-4"
    >
      {/* Search + sort row */}
      <div className="flex flex-col gap-3 md:flex-row md:items-end">
        <div className="flex flex-1 flex-col gap-1.5">
          <Label htmlFor="q">بحث</Label>
          <div className="relative">
            <Search
              className="pointer-events-none absolute top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              style={{ insetInlineStart: "0.625rem" }}
              aria-hidden
            />
            <Input
              id="q"
              value={qDraft}
              onChange={(e) => setQDraft(e.target.value)}
              placeholder="ابحث في العنوان أو الوصف…"
              className="ps-9"
            />
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="sort">الترتيب حسب</Label>
          <Select
            value={params.sort}
            onValueChange={(v) => setSort(v as SortField)}
          >
            <SelectTrigger id="sort" className="min-w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="posted_at">تاريخ النشر</SelectItem>
              <SelectItem value="budget">الميزانية</SelectItem>
              <SelectItem value="bids_count">عدد العروض</SelectItem>
              <SelectItem value="hiring_rate">نسبة التوظيف</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="order">الاتجاه</Label>
          <Select
            value={params.order}
            onValueChange={(v) => setSort(params.sort, v as SortOrder)}
          >
            <SelectTrigger id="order" className="min-w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="desc">تنازلي</SelectItem>
              <SelectItem value="asc">تصاعدي</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Filter grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="tier">المستوى</Label>
          <Select
            value={params.tier ? String(params.tier) : ANY}
            onValueChange={(v) =>
              patch({ tier: v === ANY ? undefined : (Number(v) as 1 | 2) })
            }
          >
            <SelectTrigger id="tier">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>الكل</SelectItem>
              <SelectItem value="1">Tier 1</SelectItem>
              <SelectItem value="2">Tier 2</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="site_status">حالة المشروع</Label>
          <Select
            value={params.site_status ?? ANY}
            onValueChange={(v) =>
              patch({
                site_status:
                  v === ANY ? undefined : (v as ProjectFilters["site_status"]),
              })
            }
          >
            <SelectTrigger id="site_status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>الكل</SelectItem>
              <SelectItem value="open">مفتوح</SelectItem>
              <SelectItem value="closed">مغلق</SelectItem>
              <SelectItem value="unknown">غير معروف</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="personal_status">مرحلتي</Label>
          <Select
            value={params.personal_status ?? ANY}
            onValueChange={(v) =>
              patch({ personal_status: v && v !== ANY ? v : undefined })
            }
          >
            <SelectTrigger id="personal_status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>الكل</SelectItem>
              {(statusOptions ?? []).map((s) => (
                <SelectItem key={s.key} value={s.key}>
                  {s.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="posted_within_hours">نُشر خلال</Label>
          <Select
            value={
              params.posted_within_hours
                ? String(params.posted_within_hours)
                : ANY
            }
            onValueChange={(v) =>
              patch({
                posted_within_hours: v === ANY ? undefined : Number(v),
              })
            }
          >
            <SelectTrigger id="posted_within_hours">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>أي وقت</SelectItem>
              <SelectItem value="1">آخر ساعة</SelectItem>
              <SelectItem value="6">آخر ٦ ساعات</SelectItem>
              <SelectItem value="24">آخر ٢٤ ساعة</SelectItem>
              <SelectItem value="72">آخر ٣ أيام</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <NumberField
          id="min_hiring_rate"
          label="أدنى نسبة توظيف (٪)"
          value={params.min_hiring_rate}
          min={0}
          max={100}
          placeholder="0–100"
          onCommit={(v) => patch({ min_hiring_rate: v })}
        />

        <NumberField
          id="budget_min"
          label="أدنى ميزانية"
          value={params.budget_min}
          min={0}
          onCommit={(v) => patch({ budget_min: v })}
        />
        <NumberField
          id="budget_max"
          label="أعلى ميزانية"
          value={params.budget_max}
          min={0}
          onCommit={(v) => patch({ budget_max: v })}
        />
        <NumberField
          id="bids_min"
          label="أدنى عدد عروض"
          value={params.bids_min}
          min={0}
          onCommit={(v) => patch({ bids_min: v })}
        />
        <NumberField
          id="bids_max"
          label="أعلى عدد عروض"
          value={params.bids_max}
          min={0}
          onCommit={(v) => patch({ bids_max: v })}
        />
      </div>

      {/* Toggle + clear row */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Switch
              id="qualified_only"
              checked={params.qualified_only ?? false}
              onCheckedChange={(checked) =>
                patch({ qualified_only: checked ? true : undefined })
              }
            />
            <Label htmlFor="qualified_only">المشاريع المؤهلة فقط</Label>
          </div>

          <div className="flex items-center gap-2">
            <Switch
              id="favorites_only"
              checked={params.favorites_only ?? false}
              onCheckedChange={(checked) =>
                patch({ favorites_only: checked ? true : undefined })
              }
            />
            <Label htmlFor="favorites_only">المفضّلة فقط</Label>
          </div>

          <div className="flex items-center gap-2">
            <Switch
              id="include_hidden"
              checked={params.include_hidden ?? false}
              onCheckedChange={(checked) =>
                patch({ include_hidden: checked ? true : undefined })
              }
            />
            <Label htmlFor="include_hidden">إظهار المخفية</Label>
          </div>
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={clearFilters}
          disabled={!filtersActive}
        >
          <X className="size-4" aria-hidden />
          <span>مسح الفلاتر</span>
        </Button>
      </div>
    </section>
  );
}
