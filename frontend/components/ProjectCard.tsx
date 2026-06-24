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
import { Bidi } from "@/components/Bidi";
import {
  QualifiedBadge,
  SiteStatusBadge,
} from "@/components/ProjectTable";
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

function ProjectCardItem({ p }: { p: ProjectListItem }) {
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
          <div className="flex shrink-0 items-center gap-1.5">
            <SiteStatusBadge status={p.site_status} />
            <QualifiedBadge qualified={p.qualified} />
          </div>
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
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((p) => (
        <ProjectCardItem key={p.id} p={p} />
      ))}
    </div>
  );
}
