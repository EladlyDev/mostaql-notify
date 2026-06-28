"use client";

import { useState } from "react";
import {
  Check,
  Download,
  Eye,
  FileText,
  Pencil,
  Trash2,
  X,
} from "lucide-react";

import type { AttachmentItem } from "@/lib/types";
import { attachmentDownloadUrl } from "@/lib/api";
import { formatAbsolute } from "@/lib/format";
import { Bidi } from "@/components/Bidi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const TYPE_LABEL: Record<AttachmentItem["file_type"], string> = {
  pdf: "PDF",
  docx: "DOCX",
  md: "Markdown",
};

function humanSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value % 1 === 0 ? value : value.toFixed(1)} ${units[i]}`;
}

export interface FileListProps {
  items: AttachmentItem[];
  /** Open the preview dialog for a previewable file. */
  onPreview: (item: AttachmentItem) => void;
  /** Commit a rename (wire to useRenameAttachment.mutate). */
  onRename: (attachmentId: number, originalName: string) => void;
  /** Delete a file (wire to useDeleteAttachment.mutate). */
  onDelete: (attachmentId: number) => void;
  /** Id of the row whose rename is in flight (disables that row's controls). */
  renamingId?: number | null;
  /** Id of the row whose delete is in flight. */
  deletingId?: number | null;
}

export function FileList({
  items,
  onPreview,
  onRename,
  onDelete,
  renamingId,
  deletingId,
}: FileListProps) {
  // Inline rename / delete-confirm state (which row + the draft name).
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftName, setDraftName] = useState("");
  const [confirmId, setConfirmId] = useState<number | null>(null);

  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center text-sm text-muted-foreground">
        لا توجد ملفات مرفقة بعد. ارفع ملفًا (PDF أو DOCX أو Markdown) للبدء.
      </div>
    );
  }

  function startEdit(item: AttachmentItem) {
    setConfirmId(null);
    setEditingId(item.id);
    setDraftName(item.original_name);
  }

  function commitEdit(item: AttachmentItem) {
    const next = draftName.trim();
    setEditingId(null);
    if (next && next !== item.original_name) {
      onRename(item.id, next);
    }
  }

  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {items.map((item) => {
        const editing = editingId === item.id;
        const confirming = confirmId === item.id;
        const renaming = renamingId === item.id;
        const deleting = deletingId === item.id;
        const rowBusy = renaming || deleting;

        return (
          <li
            key={item.id}
            className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="flex min-w-0 items-start gap-2.5">
              <FileText
                className="mt-0.5 size-5 shrink-0 text-muted-foreground"
                aria-hidden
              />
              <div className="min-w-0">
                {editing ? (
                  <Input
                    dir="auto"
                    autoFocus
                    value={draftName}
                    disabled={renaming}
                    onChange={(e) => setDraftName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitEdit(item);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    aria-label="اسم الملف"
                    className="h-7"
                  />
                ) : (
                  <p className="truncate text-sm font-medium">
                    <Bidi>{item.original_name}</Bidi>
                  </p>
                )}
                <p className="mt-0.5 text-xs text-muted-foreground">
                  <Bidi>{TYPE_LABEL[item.file_type]}</Bidi>
                  {" · "}
                  <Bidi>{humanSize(item.size_bytes)}</Bidi>
                  {" · "}
                  <Bidi>{formatAbsolute(item.uploaded_at)}</Bidi>
                </p>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-1">
              {editing ? (
                <>
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => commitEdit(item)}
                    disabled={renaming}
                    aria-label="حفظ الاسم"
                  >
                    <Check aria-hidden />
                  </Button>
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => setEditingId(null)}
                    disabled={renaming}
                    aria-label="إلغاء"
                  >
                    <X aria-hidden />
                  </Button>
                </>
              ) : confirming ? (
                <>
                  <span className="text-xs text-muted-foreground">حذف؟</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    onClick={() => {
                      setConfirmId(null);
                      onDelete(item.id);
                    }}
                    disabled={deleting}
                  >
                    {deleting ? "جارٍ الحذف…" : "تأكيد"}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setConfirmId(null)}
                    disabled={deleting}
                  >
                    إلغاء
                  </Button>
                </>
              ) : (
                <>
                  {item.can_preview && (
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      onClick={() => onPreview(item)}
                      disabled={rowBusy}
                      aria-label="معاينة"
                    >
                      <Eye aria-hidden />
                    </Button>
                  )}
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    disabled={rowBusy}
                    aria-label="تنزيل"
                    render={
                      <a
                        href={attachmentDownloadUrl(item.id)}
                        download={item.original_name}
                      />
                    }
                  >
                    <Download aria-hidden />
                  </Button>
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => startEdit(item)}
                    disabled={rowBusy}
                    aria-label="إعادة تسمية"
                  >
                    <Pencil aria-hidden />
                  </Button>
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => {
                      setEditingId(null);
                      setConfirmId(item.id);
                    }}
                    disabled={rowBusy}
                    aria-label="حذف"
                    className="text-destructive hover:text-destructive"
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
