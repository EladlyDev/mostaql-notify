"use client";

import { Suspense, useCallback, useState } from "react";
import { LayoutGrid, Table as TableIcon } from "lucide-react";

import { ApiError } from "@/lib/api";
import { useProjects } from "@/lib/useProjects";
import { formatNumber } from "@/lib/format";
import { Bidi } from "@/components/Bidi";
import { Filters } from "@/components/Filters";
import { ProjectCard } from "@/components/ProjectCard";
import { ProjectTable } from "@/components/ProjectTable";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";

type View = "table" | "cards";
const VIEW_KEY = "projects:view";

function readView(): View {
  if (typeof window === "undefined") return "table"; // SSR-safe default
  try {
    return window.localStorage.getItem(VIEW_KEY) === "cards" ? "cards" : "table";
  } catch {
    return "table"; // storage blocked (private mode / disabled) — fall back to the default
  }
}

/** View preference held in plain React state so a click ALWAYS re-renders and re-toggles — the
 *  source of truth is in memory, with localStorage as best-effort persistence only. (A previous
 *  version derived the view directly from localStorage via useSyncExternalStore, which wedges the
 *  toggle whenever storage throws, since the state can then never change.) The lazy initializer
 *  seeds from storage without a set-state-in-effect, and this subtree is client-rendered behind
 *  Suspense (useSearchParams), so reading storage on the first render causes no hydration mismatch. */
function useViewPreference(): [View, (v: View) => void] {
  const [view, setViewState] = useState<View>(readView);

  const setView = useCallback((v: View) => {
    setViewState(v);
    try {
      window.localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* best-effort persistence */
    }
  }, []);

  return [view, setView];
}

function ProjectsFeed() {
  const controller = useProjects();
  const {
    params,
    filtersActive,
    data,
    isLoading,
    isError,
    error,
    refetch,
    setPage,
    clearFilters,
  } = controller;

  const [view, setView] = useViewPreference();

  const total = data?.total ?? 0;
  const page = data?.page ?? params.page;
  const pageSize = data?.page_size ?? params.page_size;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const hasPrev = page > 1;
  const hasNext = page < totalPages;

  let body: React.ReactNode;

  if (isLoading) {
    body = <Loading rows={8} />;
  } else if (isError) {
    const message =
      error instanceof ApiError && error.isNetworkError
        ? "تعذّر الوصول إلى الخادم. تأكد من تشغيله ثم أعد المحاولة."
        : error instanceof ApiError
          ? error.message
          : "حدث خطأ غير متوقع أثناء جلب المشاريع.";
    body = <ErrorState message={message} onRetry={() => refetch()} />;
  } else if (total === 0 && filtersActive) {
    body = (
      <EmptyState
        title="لا نتائج مطابقة"
        message="لم تطابق أي مشاريع عوامل التصفية الحالية. جرّب توسيع النطاق."
        action={
          <Button variant="outline" size="sm" onClick={clearFilters}>
            مسح الفلاتر
          </Button>
        }
      />
    );
  } else if (total === 0) {
    body = (
      <EmptyState
        title="لا توجد مشاريع بعد"
        message="لم يتم رصد أي مشاريع حتى الآن. ستظهر هنا فور رصدها."
      />
    );
  } else {
    const items = data?.items ?? [];
    body =
      view === "table" ? (
        <ProjectTable items={items} />
      ) : (
        <ProjectCard items={items} />
      );
  }

  const showPager = !isLoading && !isError && total > 0;

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">المشاريع</h1>
          {!isLoading && !isError && (
            <p className="text-sm text-muted-foreground">
              <Bidi>{formatNumber(total)}</Bidi> مشروع
            </p>
          )}
        </div>

        <ToggleGroup
          value={[view]}
          onValueChange={(groupValue) => {
            const next = groupValue[groupValue.length - 1];
            if (next === "table" || next === "cards") setView(next);
          }}
          variant="outline"
          aria-label="طريقة العرض"
        >
          <ToggleGroupItem value="table" aria-label="عرض جدول">
            <TableIcon className="size-4" aria-hidden />
          </ToggleGroupItem>
          <ToggleGroupItem value="cards" aria-label="عرض بطاقات">
            <LayoutGrid className="size-4" aria-hidden />
          </ToggleGroupItem>
        </ToggleGroup>
      </header>

      <Filters controller={controller} />

      {body}

      {showPager && (
        <nav
          className="flex items-center justify-between gap-3"
          aria-label="ترقيم الصفحات"
        >
          <Button
            variant="outline"
            size="sm"
            disabled={!hasPrev}
            onClick={() => setPage(page - 1)}
          >
            السابق
          </Button>
          <span className="text-sm text-muted-foreground">
            صفحة <Bidi>{formatNumber(page)}</Bidi> من{" "}
            <Bidi>{formatNumber(totalPages)}</Bidi>
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={!hasNext}
            onClick={() => setPage(page + 1)}
          >
            التالي
          </Button>
        </nav>
      )}
    </div>
  );
}

export default function ProjectsPage() {
  // useProjects reads useSearchParams; wrap in Suspense per Next.js guidance.
  return (
    <Suspense fallback={<Loading rows={8} className="m-4 md:m-6" />}>
      <ProjectsFeed />
    </Suspense>
  );
}
