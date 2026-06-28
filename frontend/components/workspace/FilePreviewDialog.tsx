"use client";

import { useEffect, useState } from "react";
import { Download } from "lucide-react";

import type { AttachmentItem } from "@/lib/types";
import { attachmentDownloadUrl, attachmentPreviewUrl } from "@/lib/api";
import { Bidi } from "@/components/Bidi";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Markdown } from "@/components/workspace/Markdown";

export interface FilePreviewDialogProps {
  /** The file to preview, or null when nothing is selected. */
  attachment: AttachmentItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Modal preview for an attachment:
 *  - pdf  → inline <iframe> of the gated preview stream
 *  - md   → fetch the preview text and render via the sanitized {@link Markdown}
 *  - docx → no inline preview; show a message + download link
 */
export function FilePreviewDialog({
  attachment,
  open,
  onOpenChange,
}: FilePreviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-4 sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="pe-8">
            {attachment ? (
              <Bidi>{attachment.original_name}</Bidi>
            ) : (
              "معاينة الملف"
            )}
          </DialogTitle>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-auto">
          {attachment && <PreviewBody attachment={attachment} />}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function DownloadLink({ attachment }: { attachment: AttachmentItem }) {
  return (
    <a
      href={attachmentDownloadUrl(attachment.id)}
      download={attachment.original_name}
      className="inline-flex items-center gap-1.5 text-sm text-primary underline underline-offset-2 hover:text-primary/80"
    >
      <Download className="size-4" aria-hidden />
      <span>تنزيل الملف</span>
    </a>
  );
}

function PreviewBody({ attachment }: { attachment: AttachmentItem }) {
  if (attachment.file_type === "pdf") {
    return (
      <iframe
        src={attachmentPreviewUrl(attachment.id)}
        title={attachment.original_name}
        className="h-[70vh] w-full rounded-lg border border-border bg-muted"
      />
    );
  }

  if (attachment.file_type === "md") {
    // `key` remounts the fetcher (resetting it to "loading") when the file changes.
    return <MarkdownPreview key={attachment.id} attachment={attachment} />;
  }

  // docx (and anything else without inline preview)
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border px-6 py-12 text-center">
      <p className="text-sm text-muted-foreground">لا تتوفّر معاينة لهذا الملف.</p>
      <DownloadLink attachment={attachment} />
    </div>
  );
}

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; text: string }
  | { kind: "error" };

function MarkdownPreview({ attachment }: { attachment: AttachmentItem }) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch(attachmentPreviewUrl(attachment.id), { credentials: "include" })
      .then((res) => {
        if (!res.ok) throw new Error(`status ${res.status}`);
        return res.text();
      })
      .then((text) => {
        if (!cancelled) setState({ kind: "ready", text });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [attachment.id]);

  if (state.kind === "loading") {
    return (
      <p role="status" className="py-8 text-center text-sm text-muted-foreground">
        جارٍ تحميل المعاينة…
      </p>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border px-6 py-10 text-center">
        <p className="text-sm text-muted-foreground">تعذّر تحميل المعاينة.</p>
        <DownloadLink attachment={attachment} />
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <Markdown>{state.text}</Markdown>
    </div>
  );
}
