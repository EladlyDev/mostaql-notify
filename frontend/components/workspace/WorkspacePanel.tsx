"use client";

import { useState } from "react";

import type { AttachmentItem } from "@/lib/types";
import { useUpdatePersonal } from "@/lib/usePersonal";
import {
  useAttachments,
  useDeleteAttachment,
  useRenameAttachment,
  useUploadAttachment,
} from "@/lib/useAttachments";
import { useUploadConfig } from "@/lib/useUploadConfig";
import { MarkdownEditor } from "@/components/workspace/MarkdownEditor";
import { FileDropzone } from "@/components/workspace/FileDropzone";
import { FileList } from "@/components/workspace/FileList";
import { FilePreviewDialog } from "@/components/workspace/FilePreviewDialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const DEFAULT_ALLOWED = ["pdf", "docx", "md"];
const DEFAULT_MAX = 10 * 1024 * 1024;

/**
 * The per-project workspace (Feature 3, US2): a markdown notes editor (saved into the personal
 * record's `notes`) and a drag-and-drop file area (validated/stored server-side). Allowed types +
 * max size come from `/api/upload-config` so the hint matches server enforcement (config-driven).
 */
export function WorkspacePanel({
  projectId,
  initialNotes,
}: {
  projectId: number;
  initialNotes: string;
}) {
  // Notes: local draft, committed via the personal PATCH (notes). The panel is keyed by projectId
  // at the call site, so it remounts (re-seeding this draft) on navigation to another project.
  const [notes, setNotes] = useState(initialNotes);

  const updatePersonal = useUpdatePersonal();

  const { data: config } = useUploadConfig();
  const attachments = useAttachments(projectId);
  const upload = useUploadAttachment(projectId);
  const rename = useRenameAttachment(projectId);
  const del = useDeleteAttachment(projectId);

  const [preview, setPreview] = useState<AttachmentItem | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  return (
    <Card>
      <CardHeader>
        <CardTitle>مساحة العمل</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {/* Markdown notes */}
        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-muted-foreground">ملاحظات</h3>
          <MarkdownEditor
            value={notes}
            onChange={setNotes}
            onSave={() => updatePersonal.mutate({ projectId, patch: { notes } })}
            saving={updatePersonal.isPending}
          />
        </section>

        {/* Files */}
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-medium text-muted-foreground">الملفات</h3>
          <FileDropzone
            allowedTypes={config?.allowed_types ?? DEFAULT_ALLOWED}
            maxBytes={config?.max_bytes ?? DEFAULT_MAX}
            onFiles={(files) => files.forEach((f) => upload.mutate(f))}
            error={upload.error?.message ?? null}
            uploading={upload.isPending}
          />
          <FileList
            items={attachments.data?.items ?? []}
            onPreview={(item) => {
              setPreview(item);
              setPreviewOpen(true);
            }}
            onRename={(id, name) =>
              rename.mutate({ attachmentId: id, originalName: name })
            }
            onDelete={(id) => del.mutate(id)}
            renamingId={rename.isPending ? rename.variables?.attachmentId : null}
            deletingId={del.isPending ? del.variables : null}
          />
        </section>

        <FilePreviewDialog
          attachment={preview}
          open={previewOpen}
          onOpenChange={setPreviewOpen}
        />
      </CardContent>
    </Card>
  );
}
