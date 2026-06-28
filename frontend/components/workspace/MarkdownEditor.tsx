"use client";

import { useState } from "react";
import { Save } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Markdown } from "@/components/workspace/Markdown";

export interface MarkdownEditorProps {
  /** Current notes value (controlled). */
  value: string;
  /** Called on every keystroke with the next value. */
  onChange: (value: string) => void;
  /** Called when the user clicks Save (wire to updatePersonal(projectId, { notes })). */
  onSave: () => void;
  /** Save in flight — disables editing + shows a saving label. */
  saving?: boolean;
  /** Hard-disable the editor (e.g. while the record is still loading). */
  disabled?: boolean;
}

/**
 * Controlled Markdown notes editor with an Edit/Preview toggle. The Preview tab
 * renders through the shared sanitized {@link Markdown} component (XSS-safe).
 */
export function MarkdownEditor({
  value,
  onChange,
  onSave,
  saving = false,
  disabled = false,
}: MarkdownEditorProps) {
  const [tab, setTab] = useState<string>("edit");
  const busy = saving || disabled;
  const hasContent = value.trim().length > 0;

  return (
    <Tabs
      value={tab}
      onValueChange={(next) => setTab(String(next))}
      className="gap-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TabsList>
          <TabsTrigger value="edit">تحرير</TabsTrigger>
          <TabsTrigger value="preview">معاينة</TabsTrigger>
        </TabsList>
        <Button type="button" size="sm" onClick={onSave} disabled={busy}>
          <Save aria-hidden />
          <span>{saving ? "جارٍ الحفظ…" : "حفظ الملاحظات"}</span>
        </Button>
      </div>

      <TabsContent value="edit">
        <Textarea
          dir="auto"
          value={value}
          disabled={busy}
          onChange={(e) => onChange(e.target.value)}
          placeholder="اكتب ملاحظاتك هنا… يمكنك استخدام تنسيق Markdown (عناوين، قوائم، روابط)."
          aria-label="محرر الملاحظات"
          className="min-h-48 font-sans leading-relaxed"
        />
        <p className="mt-1.5 text-xs text-muted-foreground">
          يدعم تنسيق Markdown. انتقل إلى «معاينة» لرؤية النتيجة.
        </p>
      </TabsContent>

      <TabsContent value="preview">
        {hasContent ? (
          <div className="rounded-lg border border-border bg-card p-4">
            <Markdown>{value}</Markdown>
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
            لا توجد ملاحظات بعد. ابدأ الكتابة في تبويب «تحرير».
          </div>
        )}
      </TabsContent>
    </Tabs>
  );
}
