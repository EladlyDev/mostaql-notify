"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  CalendarCheck,
  CheckCircle2,
  FolderKanban,
  Users,
} from "lucide-react";

import { getHome } from "@/lib/api";
import type { HomeOverview } from "@/lib/types";
import { formatAbsolute, formatRelative } from "@/lib/format";
import { Bidi } from "@/components/Bidi";
import { HealthLight, type Health } from "@/components/HealthLight";
import { StatCard } from "@/components/StatCard";
import { Loading } from "@/components/states/Loading";
import { ErrorState } from "@/components/states/ErrorState";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const HEALTH_LABEL: Record<Health, string> = {
  green: "النظام يعمل",
  red: "فشل آخر فحص",
  unknown: "غير معروف",
};

const HEALTH_HINT: Record<Health, string> = {
  green: "آخر فحص اكتمل بنجاح.",
  red: "تعذّر إكمال آخر فحص أو تم حجبه.",
  unknown: "لا يوجد فحص مكتمل بعد أو الفحص قيد التنفيذ.",
};

function HealthSection({ data }: { data: HomeOverview }) {
  const health = data.health;
  const hasScrape = Boolean(data.last_successful_scrape);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="size-5 text-muted-foreground" aria-hidden />
          <span>حالة المراقبة</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-3">
          <HealthLight health={health} label={HEALTH_LABEL[health]} />
          <div className="space-y-0.5">
            <p className="text-base font-medium">{HEALTH_LABEL[health]}</p>
            <p className="text-sm text-muted-foreground">
              {HEALTH_HINT[health]}
            </p>
          </div>
        </div>

        <dl className="grid gap-4 border-t pt-4 sm:grid-cols-2">
          <div className="space-y-1">
            <dt className="text-xs text-muted-foreground">آخر فحص ناجح</dt>
            <dd className="text-sm font-medium">
              {hasScrape ? (
                <Bidi>{formatRelative(data.last_successful_scrape)}</Bidi>
              ) : (
                "لا يوجد فحص ناجح بعد"
              )}
            </dd>
            {hasScrape && (
              <dd className="text-xs text-muted-foreground">
                <Bidi>{formatAbsolute(data.last_successful_scrape)}</Bidi>
              </dd>
            )}
          </div>

          <div className="space-y-1">
            <dt className="text-xs text-muted-foreground">حالة آخر تشغيل</dt>
            <dd className="text-sm font-medium">
              {data.latest_run_status ? (
                <Bidi>{data.latest_run_status}</Bidi>
              ) : (
                "—"
              )}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

export default function HomePage() {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ["home"],
    queryFn: getHome,
  });

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:py-10">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          نظرة عامة
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          ملخّص نشاط المراقبة والمشاريع المرصودة.
        </p>
      </header>

      {isPending ? (
        <Loading rows={4} />
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : (
        <div className="space-y-6">
          {/* At-a-glance figures */}
          <section
            aria-label="أرقام موجزة"
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
          >
            <StatCard
              label="مشاريع اليوم"
              value={data.found_today}
              icon={CalendarCheck}
            />
            <StatCard
              label="مؤهلة اليوم"
              value={data.qualified_today}
              icon={CheckCircle2}
            />
            <StatCard
              label="إجمالي المشاريع"
              value={data.total_projects}
              icon={FolderKanban}
            />
            <StatCard
              label="إجمالي العملاء"
              value={data.total_clients}
              icon={Users}
            />
          </section>

          {/* Scraper health */}
          <section aria-label="حالة المراقبة">
            <HealthSection data={data} />
          </section>

          {/* Room for richer overview panels (act-now, win rate) added later. */}
        </div>
      )}
    </div>
  );
}
