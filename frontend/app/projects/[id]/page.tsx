"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ArrowUpRight, FileSearch, RotateCcw } from "lucide-react";

import { ApiError, getProject, revertAutoStatus } from "@/lib/api";
import { useLifecycle } from "@/lib/useLifecycle";
import type { ProjectDetail, ProjectListItem } from "@/lib/types";
import {
  formatAbsolute,
  formatBudget,
  formatNumber,
  formatRelative,
} from "@/lib/format";
import { Bidi } from "@/components/Bidi";
import { ClientPanel } from "@/components/ClientPanel";
import { PersonalPanel } from "@/components/personal/PersonalPanel";
import { WorkspacePanel } from "@/components/workspace/WorkspacePanel";
import { FreshnessBadge } from "@/components/score/FreshnessBadge";
import { OutcomeBadge } from "@/components/score/OutcomeBadge";
import { ScoreBars } from "@/components/score/ScoreBars";
import { BidChart } from "@/components/lifecycle/BidChart";
import { StatusTimeline } from "@/components/lifecycle/StatusTimeline";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const DASH = "—";

/** Compact meta cell: muted label above a value. */
function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium">{children}</span>
    </div>
  );
}

/** One row in the "other projects by this client" list. */
function RelatedProjectRow({ project }: { project: ProjectListItem }) {
  return (
    <Link
      href={`/projects/${project.id}`}
      className="flex items-center justify-between gap-3 rounded-lg px-3 py-2 ring-1 ring-foreground/10 transition-colors hover:bg-muted/50"
    >
      <span className="min-w-0 flex-1 truncate text-sm font-medium">
        {project.title ?? "مشروع بدون عنوان"}
      </span>
      <span className="shrink-0 text-xs text-muted-foreground">
        <Bidi>
          {formatBudget(project.budget_min, project.budget_max, project.currency)}
        </Bidi>
      </span>
    </Link>
  );
}

const scoreFmt = new Intl.NumberFormat("ar-EG", { maximumFractionDigits: 0 });

/**
 * Undo a watcher-applied automatic status change (FR-031). Shown only when the
 * personal record carries an `auto_status_at` stamp; POSTs the revert and
 * refreshes the detail / personal / feed caches on success.
 */
function AutoStatusRevert({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const revert = useMutation({
    mutationFn: () => revertAutoStatus(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["personal", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["board"] });
    },
  });

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => revert.mutate()}
      disabled={revert.isPending}
    >
      <RotateCcw aria-hidden />
      تراجع عن التغيير التلقائي
    </Button>
  );
}

/** Opportunity score headline + the explainable per-component breakdown. */
function ScoreCard({ data }: { data: ProjectDetail }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>نقاط الفرصة</CardTitle>
          {data.score !== null && data.score !== undefined && (
            <span className="text-2xl font-semibold tabular-nums">
              <Bidi>{scoreFmt.format(data.score)}</Bidi>
              <span className="text-sm font-normal text-muted-foreground">
                {" "}
                / ١٠٠
              </span>
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {data.score_breakdown ? (
          <ScoreBars breakdown={data.score_breakdown} />
        ) : (
          <p className="text-sm text-muted-foreground">
            لم يُحتسب لهذا المشروع نقاط بعد.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** Bid trajectory + status timeline + outcome (GET /lifecycle). */
function LifecycleCard({ projectId }: { projectId: number }) {
  const { data, isPending, error, refetch } = useLifecycle(projectId);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>المسار الزمني</CardTitle>
          {data?.outcome && <OutcomeBadge outcome={data.outcome} />}
        </div>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <Loading rows={3} />
        ) : error ? (
          <ErrorState
            title="تعذّر تحميل المسار الزمني"
            onRetry={() => {
              void refetch();
            }}
          />
        ) : (
          <div className="flex flex-col gap-6">
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-medium text-muted-foreground">
                مسار العروض
              </h3>
              <BidChart snapshots={data.snapshots} />
            </section>
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-medium text-muted-foreground">
                تغيّرات الحالة
              </h3>
              <StatusTimeline events={data.status_timeline} />
            </section>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ProjectDetailView({ data }: { data: ProjectDetail }) {
  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight break-words">
            {data.title ?? "مشروع بدون عنوان"}
          </h1>
          {data.tier_label && (
            <Badge variant="secondary">{data.tier_label}</Badge>
          )}
          {data.qualified && <Badge>مؤهَّل</Badge>}
          {data.site_status && (
            <Badge variant="outline">{data.site_status}</Badge>
          )}
          <FreshnessBadge freshness={data.freshness} />
          <OutcomeBadge outcome={data.outcome} />
        </div>
        {data.url && (
          <a
            href={data.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex w-fit items-center gap-1 text-sm text-primary hover:underline"
          >
            <span>افتح على مستقل</span>
            <ArrowUpRight className="size-4" aria-hidden />
          </a>
        )}
      </header>

      {/* Personal CRM controls (Feature 3, US1) */}
      {data.personal && (
        <div className="flex flex-col gap-2">
          <PersonalPanel
            key={data.id}
            projectId={data.id}
            personal={data.personal}
          />
          {/* Undo an automatic (watcher-applied) status change — Feature 4 FR-031. */}
          {data.personal.auto_status_at && (
            <div className="flex justify-end">
              <AutoStatusRevert projectId={data.id} />
            </div>
          )}
        </div>
      )}

      {/* Opportunity score + explainable breakdown (Feature 4, US1) */}
      <ScoreCard data={data} />

      {/* Lifecycle: bid trajectory, status timeline, outcome (Feature 4, US2) */}
      <LifecycleCard projectId={data.id} />

      {/* Meta row */}
      <Card>
        <CardContent>
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
            <Meta label="الميزانية">
              <Bidi>
                {formatBudget(data.budget_min, data.budget_max, data.currency)}
              </Bidi>
            </Meta>
            <Meta label="عدد العروض">
              {data.bids_count === null || data.bids_count === undefined ? (
                DASH
              ) : (
                <Bidi>{formatNumber(data.bids_count)}</Bidi>
              )}
            </Meta>
            <Meta label="نُشر">
              {data.posted_at ? (
                <span className="flex flex-col">
                  <Bidi>{formatRelative(data.posted_at)}</Bidi>
                  <span className="text-xs font-normal text-muted-foreground">
                    <Bidi>{formatAbsolute(data.posted_at)}</Bidi>
                  </span>
                </span>
              ) : (
                DASH
              )}
            </Meta>
            <Meta label="التصنيف">{data.category ?? DASH}</Meta>
          </div>

          {data.skills && data.skills.length > 0 && (
            <div className="mt-4 flex flex-col gap-1.5">
              <span className="text-xs text-muted-foreground">المهارات</span>
              <div className="flex flex-wrap gap-1.5">
                {data.skills.map((skill) => (
                  <Badge key={skill} variant="outline">
                    {skill}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Description */}
      <Card>
        <CardHeader>
          <CardTitle>وصف المشروع</CardTitle>
        </CardHeader>
        <CardContent>
          {data.description ? (
            <p
              dir="rtl"
              className="text-sm leading-relaxed break-words whitespace-pre-wrap"
            >
              {data.description}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">لا يوجد وصف</p>
          )}
        </CardContent>
      </Card>

      {/* Per-project workspace: markdown notes + file attachments (Feature 3, US2) */}
      {data.personal && (
        <WorkspacePanel
          key={data.id}
          projectId={data.id}
          initialNotes={data.personal.notes}
        />
      )}

      {/* Client reputation panel */}
      <ClientPanel client={data.client} />

      {/* Other projects by the same client */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">مشاريع أخرى لنفس العميل</h2>
        {data.same_client_projects.length > 0 ? (
          <div className="flex flex-col gap-2">
            {data.same_client_projects.map((project) => (
              <RelatedProjectRow key={project.id} project={project} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">لا مشاريع أخرى</p>
        )}
      </section>
    </div>
  );
}

export default function ProjectDetailPage() {
  // Next 16: read route params in a client component via useParams (no await).
  const params = useParams<{ id: string }>();
  const id = params.id;

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["project", id],
    queryFn: () => getProject(id),
    enabled: Boolean(id),
  });

  if (isPending) {
    return (
      <div className="mx-auto w-full max-w-4xl px-4 py-10">
        <Loading rows={6} />
      </div>
    );
  }

  if (error) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <div className="mx-auto w-full max-w-4xl px-4 py-10">
          <EmptyState
            icon={FileSearch}
            title="المشروع غير موجود"
            message="ربما حُذف المشروع أو أن الرابط غير صحيح."
            action={
              <Link
                href="/projects"
                className="text-sm text-primary hover:underline"
              >
                العودة إلى المشاريع
              </Link>
            }
          />
        </div>
      );
    }

    const isNetwork = error instanceof ApiError && error.isNetworkError;
    return (
      <div className="mx-auto w-full max-w-4xl px-4 py-10">
        <ErrorState
          title={
            isNetwork ? "تعذّر الاتصال بالخادم" : "تعذّر تحميل المشروع"
          }
          onRetry={() => {
            void refetch();
          }}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-10">
      <ProjectDetailView data={data} />
    </div>
  );
}
