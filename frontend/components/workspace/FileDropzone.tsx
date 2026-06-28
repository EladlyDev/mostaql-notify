"use client";

import { useRef, useState } from "react";
import { AlertTriangle, Upload } from "lucide-react";

import { cn } from "@/lib/utils";

// Map an allowed-type token (the AttachmentItem.file_type values) to a label
// and the matching file-extension(s) for the <input accept> hint. The SERVER is
// the validation authority — this is only a client-side affordance.
const TYPE_META: Record<string, { label: string; ext: string }> = {
  pdf: { label: "PDF", ext: ".pdf" },
  docx: { label: "DOCX", ext: ".docx" },
  md: { label: "Markdown", ext: ".md" },
};

function humanSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
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

export interface FileDropzoneProps {
  /** Allowed file_type tokens, e.g. ["pdf", "docx", "md"]. Client hint only. */
  allowedTypes: string[];
  /** Max upload size in bytes — shown as a hint; server enforces it. */
  maxBytes: number;
  /** Called with the dropped/selected files (wire to the upload mutation). */
  onFiles: (files: File[]) => void;
  /** Server rejection message to surface (e.g. mutation.error?.message). */
  error?: string | null;
  /** Upload in flight. */
  uploading?: boolean;
  /** Disable the whole control. */
  disabled?: boolean;
}

/**
 * Drag-and-drop upload area with a hidden <input type=file> fallback. Validation
 * authority is the server: wrong type → 400, too large → 413; pass the upload
 * mutation's error message via `error` to display the rejection.
 */
export function FileDropzone({
  allowedTypes,
  maxBytes,
  onFiles,
  error,
  uploading = false,
  disabled = false,
}: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const blocked = disabled || uploading;

  const labels = allowedTypes
    .map((t) => TYPE_META[t]?.label ?? t.toUpperCase())
    .join("، ");
  const accept = allowedTypes
    .map((t) => TYPE_META[t]?.ext)
    .filter((e): e is string => Boolean(e))
    .join(",");

  function emit(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    onFiles(Array.from(fileList));
  }

  function openPicker() {
    if (blocked) return;
    inputRef.current?.click();
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        role="button"
        tabIndex={blocked ? -1 : 0}
        aria-disabled={blocked || undefined}
        onClick={openPicker}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            openPicker();
          }
        }}
        onDragOver={(e) => {
          if (blocked) return;
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          setDragging(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (blocked) return;
          emit(e.dataTransfer.files);
        }}
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-10 text-center transition-colors outline-none",
          "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
          dragging
            ? "border-primary bg-primary/5"
            : "border-border hover:bg-muted/50",
          blocked && "pointer-events-none opacity-60"
        )}
      >
        <Upload className="size-7 text-muted-foreground" aria-hidden />
        <p className="text-sm font-medium">
          {uploading ? "جارٍ الرفع…" : "اسحب الملفات هنا أو انقر للاختيار"}
        </p>
        <p className="text-xs text-muted-foreground">
          الأنواع المسموحة: {labels} — الحد الأقصى للحجم: {humanSize(maxBytes)}
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accept || undefined}
          disabled={blocked}
          className="sr-only"
          aria-label="اختيار ملف للرفع"
          onChange={(e) => {
            emit(e.target.files);
            // Reset so re-selecting the same file fires change again.
            e.target.value = "";
          }}
        />
      </div>

      {error && (
        <p
          role="alert"
          className="flex items-start gap-1.5 text-xs font-medium text-destructive"
        >
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>{error}</span>
        </p>
      )}
    </div>
  );
}
