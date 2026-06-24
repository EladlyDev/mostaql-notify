import type { ReactNode } from "react";
import { BadgeCheck } from "lucide-react";

import type { ClientPanel as ClientPanelData } from "@/lib/types";
import {
  formatAbsolute,
  formatHiringRate,
  formatNumber,
} from "@/lib/format";
import { Bidi } from "@/components/Bidi";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const DASH = "—";

/** A single labelled stat. `value` is already-formatted display content. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{children}</dd>
    </div>
  );
}

/** Format a possibly-null number as a bidi-isolated localized number, or "—".
 *  Never coerces a missing value to 0. */
function num(n: number | null | undefined): ReactNode {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH;
  return <Bidi>{formatNumber(n)}</Bidi>;
}

/**
 * Client reputation panel. Renders every field defensively: any missing value
 * becomes "—" (or a friendly Arabic note), and missing numerics are NEVER
 * shown as 0.
 */
export function ClientPanel({ client }: { client: ClientPanelData | null }) {
  if (!client) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>العميل</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            لا توجد بيانات عن العميل
          </p>
        </CardContent>
      </Card>
    );
  }

  // Rating line: "4.8 (12 تقييم)" — each part null-safe.
  const ratingValue =
    client.avg_rating === null || client.avg_rating === undefined
      ? null
      : client.avg_rating;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <span>{client.name ?? "عميل غير معروف"}</span>
          {client.verified && (
            <Badge variant="secondary">
              <BadgeCheck className="size-3" aria-hidden />
              موثّق
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
          <Field label="معدل التوظيف">
            {/* null → "لم يحسب بعد" (never 0) */}
            <Bidi>{formatHiringRate(client.hiring_rate)}</Bidi>
          </Field>

          <Field label="المشاريع المنشورة">{num(client.projects_posted)}</Field>
          <Field label="المشاريع المفتوحة">{num(client.projects_open)}</Field>
          <Field label="مرات التوظيف">{num(client.hires_count)}</Field>

          <Field label="متوسط التقييم">
            {ratingValue === null ? (
              DASH
            ) : (
              <span className="flex items-baseline gap-1">
                <Bidi>{formatNumber(ratingValue)}</Bidi>
                <span className="text-xs text-muted-foreground">
                  ({num(client.reviews_count)} تقييم)
                </span>
              </span>
            )}
          </Field>

          <Field label="إجمالي الإنفاق">{num(client.total_spent)}</Field>

          <Field label="عضو منذ">
            {client.member_since ? (
              <Bidi>{formatAbsolute(client.member_since)}</Bidi>
            ) : (
              DASH
            )}
          </Field>

          <Field label="الدولة">{client.country ?? "غير معروف"}</Field>

          <Field label="التوثيق">
            {client.verified ? "موثّق" : "غير موثّق"}
          </Field>
        </dl>
      </CardContent>
    </Card>
  );
}
