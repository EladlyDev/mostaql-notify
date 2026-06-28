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
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const DASH = "—";

type BadgeVariant =
  | "default"
  | "secondary"
  | "destructive"
  | "outline"
  | "ghost"
  | "link";

export function siteStatusBadge(status: string): {
  label: string;
  variant: BadgeVariant;
} {
  switch (status) {
    case "open":
      return { label: "مفتوح", variant: "default" };
    case "closed":
      return { label: "مغلق", variant: "destructive" };
    default:
      return { label: "غير معروف", variant: "outline" };
  }
}

export function SiteStatusBadge({ status }: { status: string }) {
  const { label, variant } = siteStatusBadge(status);
  return <Badge variant={variant}>{label}</Badge>;
}

export function QualifiedBadge({ qualified }: { qualified: boolean }) {
  return qualified ? (
    <Badge variant="default">مؤهل</Badge>
  ) : (
    <Badge variant="outline" className="text-muted-foreground">
      غير مؤهل
    </Badge>
  );
}

export function ProjectTable({ items }: { items: ProjectListItem[] }) {
  const { data: statuses } = useStatuses();
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-start">المتابعة</TableHead>
            <TableHead className="text-start">المشروع</TableHead>
            <TableHead className="text-start">العميل</TableHead>
            <TableHead className="text-start">الميزانية</TableHead>
            <TableHead className="text-start">المستوى</TableHead>
            <TableHead className="text-start">العروض</TableHead>
            <TableHead className="text-start">النشر</TableHead>
            <TableHead className="text-start">الحالة</TableHead>
            <TableHead className="text-start">التأهل</TableHead>
            <TableHead className="text-start">
              <span className="sr-only">رابط مستقل</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((p) => (
            <TableRow key={p.id} className="align-top">
              <TableCell>
                <div className="flex items-center gap-1.5">
                  <FavoriteToggle projectId={p.id} favorite={p.favorite} size="icon-sm" />
                  <div className="flex flex-col items-start gap-1">
                    <Badge variant="secondary" className="whitespace-nowrap">
                      <Bidi>{p.personal_status_label}</Bidi>
                    </Badge>
                    {p.hidden && (
                      <Badge variant="outline" className="text-muted-foreground">
                        مخفي
                      </Badge>
                    )}
                  </div>
                  <ProjectRowMenu item={p} statuses={statuses ?? []} />
                </div>
              </TableCell>
              <TableCell className="max-w-xs whitespace-normal">
                <Link
                  href={`/projects/${p.id}`}
                  className="font-medium text-foreground hover:underline"
                >
                  <Bidi className="line-clamp-2 break-words">
                    {p.title ?? DASH}
                  </Bidi>
                </Link>
              </TableCell>
              <TableCell>
                <div className="flex flex-col">
                  <span className="text-sm">
                    <Bidi>{p.client_name ?? DASH}</Bidi>
                  </span>
                  <span className="text-xs text-muted-foreground">
                    نسبة التوظيف: <Bidi>{formatHiringRate(p.client_hiring_rate)}</Bidi>
                  </span>
                </div>
              </TableCell>
              <TableCell className="whitespace-nowrap text-sm">
                <Bidi>{formatBudget(p.budget_min, p.budget_max, p.currency)}</Bidi>
              </TableCell>
              <TableCell className="whitespace-nowrap text-sm">
                {p.tier_label ? <Bidi>{p.tier_label}</Bidi> : DASH}
              </TableCell>
              <TableCell className="text-sm tabular-nums">
                {p.bids_count != null ? (
                  <Bidi>{formatNumber(p.bids_count)}</Bidi>
                ) : (
                  DASH
                )}
              </TableCell>
              <TableCell className="whitespace-nowrap text-sm">
                <span title={formatAbsolute(p.posted_at)}>
                  <Bidi>{formatRelative(p.posted_at)}</Bidi>
                </span>
                <span className="block text-xs text-muted-foreground">
                  <Bidi>{formatAbsolute(p.posted_at)}</Bidi>
                </span>
              </TableCell>
              <TableCell>
                <SiteStatusBadge status={p.site_status} />
              </TableCell>
              <TableCell>
                <QualifiedBadge qualified={p.qualified} />
              </TableCell>
              <TableCell>
                {p.url ? (
                  <a
                    href={p.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center text-muted-foreground hover:text-foreground"
                    aria-label="فتح المشروع على مستقل"
                    title="فتح على مستقل"
                  >
                    <ExternalLink className="size-4" aria-hidden />
                  </a>
                ) : (
                  DASH
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
