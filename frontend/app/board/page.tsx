"use client";

import { Board } from "@/components/board/Board";
import { PauseControl } from "@/components/PauseControl";

// The Kanban pipeline board (Feature 3, US3). `Board` self-fetches via useBoard() and renders its
// own loading / empty / error states. The pause/resume control mirrors the bot + Home.
export default function BoardPage() {
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">اللوحة</h1>
          <p className="text-sm text-muted-foreground">
            المشاريع التي أتابعها، موزّعة على مراحل خط الأنابيب.
          </p>
        </div>
        <PauseControl />
      </header>

      <Board />
    </div>
  );
}
