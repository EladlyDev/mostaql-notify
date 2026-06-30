"use client";

import { Suspense } from "react";

import { ApiError } from "@/lib/api";
import { useAnalytics } from "@/lib/useAnalytics";
import { Bidi } from "@/components/Bidi";
import { DateRangeFilter } from "@/components/analytics/DateRangeFilter";
import { Heatmap } from "@/components/analytics/Heatmap";
import { VolumeChart } from "@/components/analytics/VolumeChart";
import { BudgetChart } from "@/components/analytics/BudgetChart";
import { CompetitionChart } from "@/components/analytics/CompetitionChart";
import { OutcomesPanel } from "@/components/analytics/OutcomesPanel";
import { FunnelChart } from "@/components/analytics/FunnelChart";
import { TipsPanel } from "@/components/analytics/TipsPanel";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";

function AnalyticsSection() {
  const controller = useAnalytics();
  const { data, isLoading, isError, error } = controller;

  let body: React.ReactNode;

  if (isLoading) {
    body = <Loading rows={8} />;
  } else if (isError) {
    const message =
      error instanceof ApiError && error.isNetworkError
        ? "تعذّر الوصول إلى الخادم. تأكد من تشغيله ثم أعد المحاولة."
        : error instanceof ApiError
          ? error.message
          : "حدث خطأ غير متوقع أثناء جلب التحليلات.";
    body = <ErrorState message={message} onRetry={() => controller.refetch()} />;
  } else if (data) {
    // Distinguish "the selected range has no data at all" from each section's own
    // "not enough data yet" support gate (US7 / T056).
    const rangeEmpty =
      data.heatmap.total === 0 &&
      data.volume.by_day.length === 0 &&
      data.budget.total === 0 &&
      data.funnel.seen === 0;

    body = rangeEmpty ? (
      <EmptyState
        title="لا توجد بيانات في النطاق المحدّد"
        message="لم تُرصد أي مشاريع ضمن هذا النطاق الزمني. وسّع النطاق أو انتظر دورة جمع جديدة."
      />
    ) : (
      <div className="flex flex-col gap-6">
        <Heatmap data={data.heatmap} />
        <VolumeChart data={data.volume} />
        <BudgetChart data={data.budget} />
        <CompetitionChart data={data.competition} />
        <OutcomesPanel data={data.outcomes} />
        <FunnelChart data={data.funnel} />
        <TipsPanel tips={data.tips} />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 md:p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-bold">التحليلات</h1>
        <p className="text-sm text-muted-foreground">
          رؤى مستخلصة مما جمعه النظام — أوقات النشر، المنافسة، النتائج، ومسارك.
          {data && (
            <>
              {" "}
              النطاق:{" "}
              <Bidi>{data.range.date_from}</Bidi> – <Bidi>{data.range.date_to}</Bidi> (
              <Bidi>{data.range.timezone}</Bidi>)
            </>
          )}
        </p>
      </header>

      <DateRangeFilter controller={controller} />

      {body}
    </div>
  );
}

export default function AnalyticsPage() {
  // useAnalytics reads useSearchParams; wrap in Suspense per Next.js guidance.
  return (
    <Suspense fallback={<Loading rows={8} className="m-4 md:m-6" />}>
      <AnalyticsSection />
    </Suspense>
  );
}
