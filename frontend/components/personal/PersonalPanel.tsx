"use client";

import { useEffect, useRef, useState } from "react";

import type { PersonalRecord } from "@/lib/types";
import { useStatuses } from "@/lib/useStatuses";
import {
  useHide,
  useSetOutcome,
  useSetStatus,
  useSetTags,
  useUnhide,
} from "@/lib/usePersonal";
import { formatAbsolute, formatRelative } from "@/lib/format";
import { Bidi } from "@/components/Bidi";
import { FavoriteToggle } from "@/components/personal/FavoriteToggle";
import { StatusSelect } from "@/components/personal/StatusSelect";
import { TagEditor } from "@/components/personal/TagEditor";
import { OutcomeFields, type OutcomePatch } from "@/components/personal/OutcomeFields";
import { HideButton } from "@/components/personal/HideButton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * The owner's CRM controls for one project (Feature 3, US1) — favorite, pipeline stage, tags,
 * applied date, won/lost outcome, hide — plus a small status-changed timeline. Mutations route
 * through the `usePersonal` hooks, which invalidate `["project", id]` so this card reflects the
 * authoritative record after each change. Outcome fields keep local state and commit on a short
 * debounce so typing an amount/reason isn't a write per keystroke.
 */
export function PersonalPanel({
  projectId,
  personal,
}: {
  projectId: number;
  personal: PersonalRecord;
}) {
  const { data: statuses } = useStatuses();
  const setStatus = useSetStatus();
  const setTags = useSetTags();
  const setOutcome = useSetOutcome();
  const hide = useHide();
  const unhide = useUnhide();

  // Local outcome draft (debounced commit) so the inputs stay smooth while typing. The panel is
  // keyed by projectId at the call site, so it remounts (re-seeding this state) on navigation.
  const [outcome, setOutcome_] = useState<OutcomePatch>({
    won_amount: personal.won_amount,
    lost_reason: personal.lost_reason,
  });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const onOutcomeChange = (patch: OutcomePatch) => {
    setOutcome_((prev) => ({ ...prev, ...patch }));
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setOutcome.mutate({
        projectId,
        wonAmount: patch.won_amount ?? undefined,
        lostReason: patch.lost_reason ?? undefined,
      });
    }, 500);
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>متابعتي</CardTitle>
          <div className="flex items-center gap-2">
            <FavoriteToggle projectId={projectId} favorite={personal.favorite} />
            <HideButton
              hidden={personal.hidden}
              onToggle={() =>
                (personal.hidden ? unhide : hide).mutate(projectId)
              }
            />
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <span className="text-xs text-muted-foreground">المرحلة</span>
            <StatusSelect
              value={personal.status}
              statuses={statuses ?? []}
              onChange={(status) => setStatus.mutate({ projectId, status })}
            />
          </div>

          <OutcomeFields
            status={personal.status}
            wonAmount={outcome.won_amount ?? null}
            lostReason={outcome.lost_reason ?? null}
            onChange={onOutcomeChange}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-muted-foreground">الوسوم</span>
          <TagEditor
            value={personal.tags}
            onChange={(tags) => setTags.mutate({ projectId, tags })}
          />
        </div>

        {/* Status-changed / applied timeline (FR-008). */}
        <dl className="grid grid-cols-1 gap-3 border-t pt-3 text-sm sm:grid-cols-2">
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted-foreground">تاريخ التقديم</dt>
            <dd>
              {personal.applied_at ? (
                <Bidi>{formatAbsolute(personal.applied_at)}</Bidi>
              ) : (
                <span className="text-muted-foreground">لم يُسجّل بعد</span>
              )}
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted-foreground">آخر تغيير للمرحلة</dt>
            <dd>
              {personal.status_changed_at ? (
                <span title={formatAbsolute(personal.status_changed_at)}>
                  <Bidi>{formatRelative(personal.status_changed_at)}</Bidi>
                </span>
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}
