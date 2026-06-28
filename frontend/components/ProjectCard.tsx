"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";

import type { ProjectListItem } from "@/lib/types";
import {
  formatAbsolute,
  formatBudget,
  formatHiringRate,
  formatNumber,
  formatRelative,
} from "@/lib/format";
import { useStatuses } from "@/lib/useStatuses";
import { Bidi } from "@/components/Bidi";
import { FavoriteToggle } from "@/components/personal/FavoriteToggle";
import { ProjectRowMenu } from "@/components/personal/ProjectRowMenu";
import {
  QualifiedBadge,
  SiteStatusBadge,
} from "@/components/ProjectTable";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const DASH = "—";

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  );
}

function ProjectCardItem({
  p,
  statuses,
}: {
  p: ProjectListItem;
  statuses: { key: string; label: string }[];
}) {
  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="min-w-0 text-base leading-snug">
            <Link
              href={`/projects/${p.id}`}
              className="hover:underline"
            >
              <Bidi className="line-clamp-2 break-words">
                {p.title ?? DASH}
              </Bidi>
            </Link>
          </CardTitle>
          <div className="flex shrink-0 items-center gap-1">
            <FavoriteToggle projectId={p.id} favorite={p.favorite} size="icon-sm" />
            <ProjectRowMenu item={p} statuses={statuses} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary">
            <Bidi>{p.personal_status_label}</Bidi>
          </Badge>
          {p.hidden && (
            <Badge variant="outline" className="text-muted-foreground">
              مخفي
            </Badge>
          )}
          <SiteStatusBadge status={p.site_status} />
          <QualifiedBadge qualified={p.qualified} />
        </div>
        <p className="text-sm text-muted-foreground">
          <Bidi>{p.client_name ?? DASH}</Bidi>
          {" · "}
          <span>نسبة التوظيف: </span>
          <Bidi>{formatHiringRate(p.client_hiring_rate)}</Bidi>
        </p>
      </CardHeader>

      <CardContent className="grid flex-1 grid-cols-2 gap-3">
        <Field
          label="الميزانية"
          value={
            <Bidi>{formatBudget(p.budget_min, p.budget_max, p.currency)}</Bidi>
          }
        />
        <Field
          label="المستوى"
          value={p.tier_label ? <Bidi>{p.tier_label}</Bidi> : DASH}
        />
        <Field
          label="عدد العروض"
          value={
            p.bids_count != null ? (
              <Bidi>{formatNumber(p.bids_count)}</Bidi>
            ) : (
              DASH
            )
          }
        />
        <Field
          label="النشر"
          value={
            <span title={formatAbsolute(p.posted_at)}>
              <Bidi>{formatRelative(p.posted_at)}</Bidi>
            </span>
          }
        />
        <div className="col-span-2">
          <span className="text-xs text-muted-foreground">
            <Bidi>{formatAbsolute(p.posted_at)}</Bidi>
          </span>
        </div>
      </CardContent>

      <CardFooter>
        {p.url ? (
          <a
            href={p.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ExternalLink className="size-4" aria-hidden />
            <span>عرض على مستقل</span>
          </a>
        ) : null}
      </CardFooter>
    </Card>
  );
}

export function ProjectCard({ items }: { items: ProjectListItem[] }) {
  const { data: statuses } = useStatuses();
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((p) => (
        <ProjectCardItem key={p.id} p={p} statuses={statuses ?? []} />
      ))}
    </div>
  );
}
