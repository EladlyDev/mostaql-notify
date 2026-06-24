"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getSettings } from "@/lib/api";
import type { SettingsResponse } from "@/lib/types";
import { Loading } from "@/components/states/Loading";
import { ErrorState } from "@/components/states/ErrorState";
import { SettingsForm } from "@/components/SettingsForm";

const SETTINGS_KEY = ["settings"] as const;

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: getSettings,
  });

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-10">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">الإعدادات</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          اضبط معايير المراقبة والتقييم. تُطبَّق التغييرات على العامل (worker) في
          الدورة التالية بعد الحفظ.
        </p>
      </header>

      {query.isPending ? (
        <Loading rows={6} />
      ) : query.isError ? (
        <ErrorState onRetry={() => query.refetch()} />
      ) : (
        <SettingsForm
          // Remount when the loaded server state changes so the form resets
          // its local (string) state cleanly to the new baseline.
          key={query.dataUpdatedAt}
          data={query.data}
          onSaved={(next: SettingsResponse) =>
            queryClient.setQueryData(SETTINGS_KEY, next)
          }
        />
      )}
    </div>
  );
}
