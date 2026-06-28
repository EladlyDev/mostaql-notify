"""Attachment endpoints (Feature 3, US2) — workspace file upload / list / rename / delete / serve.

Security-critical (constitution IX). Uploads are validated by type + magic bytes + size in the
storage layer; nothing is stored on any validation failure. Files live outside any public web path
and are streamed back only here, with an explicit ``media_type`` and ``X-Content-Type-Options:
nosniff`` so a browser never sniffs or executes them. Auth is applied at include time in ``app.py``
(``dependencies=[Depends(require_auth)]``); this router never re-adds it.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config.settings_store import SettingsStore
from ...db.models import Attachment, Project
from ...storage import attachments as storage
from ..deps import get_db
from ..schemas import (
    AttachmentItem,
    AttachmentListResponse,
    AttachmentRename,
    UploadConfig,
)

router = APIRouter(tags=["attachments"])

NOSNIFF = {"X-Content-Type-Options": "nosniff"}
_PREVIEWABLE = ("pdf", "md")
_READ_CHUNK = 64 * 1024


@router.get("/api/upload-config", response_model=UploadConfig)
def get_upload_config(db: Annotated[Session, Depends(get_db)]) -> UploadConfig:
    """The configured allowed types + max size, so the dropzone hint matches server enforcement."""
    store = SettingsStore(db)
    return UploadConfig(
        allowed_types=store.get_json("upload_allowed_types"),
        max_bytes=store.get_int("upload_max_bytes"),
    )


def _to_item(att: Attachment) -> AttachmentItem:
    """Build the list/detail DTO; ``can_preview`` is true for the inline-previewable types."""
    return AttachmentItem(
        id=att.id,
        project_id=att.project_id,
        original_name=att.original_name,
        file_type=att.file_type,
        size_bytes=att.size_bytes,
        uploaded_at=att.uploaded_at,
        can_preview=att.file_type in _PREVIEWABLE,
    )


def _get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "No such project")
    return project


def _get_attachment_or_404(db: Session, attachment_id: int) -> Attachment:
    att = db.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(404, "No such attachment")
    return att


async def _read_capped(upload: UploadFile, limit: int) -> bytes:
    """Read at most ``limit`` bytes so an oversize upload is never buffered unbounded.

    The caller passes ``limit = max_bytes + 1``; reading one byte past the cap lets ``validate``
    detect the overflow (``len(data) > max_bytes``) without holding the whole payload in memory.
    """
    chunks: list[bytes] = []
    remaining = limit
    while remaining > 0:
        chunk = await upload.read(min(_READ_CHUNK, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


@router.get(
    "/api/projects/{project_id}/attachments", response_model=AttachmentListResponse
)
def list_attachments(
    project_id: int, db: Annotated[Session, Depends(get_db)]
) -> AttachmentListResponse:
    """List a project's attachments (newest first). 404 if the project does not exist."""
    _get_project_or_404(db, project_id)
    rows = db.scalars(
        select(Attachment)
        .where(Attachment.project_id == project_id)
        .order_by(Attachment.uploaded_at.desc(), Attachment.id.desc())
    ).all()
    return AttachmentListResponse(items=[_to_item(a) for a in rows])


@router.post(
    "/api/projects/{project_id}/attachments",
    response_model=AttachmentItem,
    status_code=201,
)
async def upload_attachment(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> AttachmentItem:
    """Validate + store an uploaded file (PDF/DOCX/MD), then record its metadata.

    Validation order: extension → magic bytes → size. Unsupported type → 400; oversize → 413;
    nothing is written to disk and no row is inserted on any failure. 404 if the project is missing.
    """
    _get_project_or_404(db, project_id)

    store = SettingsStore(db)
    max_bytes = store.get_int("upload_max_bytes")
    allowed_types = store.get_json("upload_allowed_types")

    # Bounded read (≤ max_bytes + 1) — never buffer an oversize payload in full.
    data = await _read_capped(file, max_bytes + 1)

    try:
        file_type, content_type = storage.validate(
            file.filename or "",
            file.content_type,
            data,
            allowed_types=allowed_types,
            max_bytes=max_bytes,
        )
    except storage.FileTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc
    except storage.UnsupportedTypeError as exc:
        raise HTTPException(400, str(exc)) from exc

    # Only now — after a clean validation — does anything touch disk or the DB.
    stored_name = storage.save(project_id, file_type, data)
    att = Attachment(
        project_id=project_id,
        original_name=file.filename or stored_name,
        stored_name=stored_name,
        file_type=file_type,
        content_type=content_type,
        size_bytes=len(data),
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return _to_item(att)


@router.patch("/api/attachments/{attachment_id}", response_model=AttachmentItem)
def rename_attachment(
    attachment_id: int,
    body: AttachmentRename,
    db: Annotated[Session, Depends(get_db)],
) -> AttachmentItem:
    """Rename the **display** name only; the stored file on disk is never touched. 422 if blank."""
    att = _get_attachment_or_404(db, attachment_id)
    new_name = body.original_name.strip()
    if not new_name:
        raise HTTPException(422, "original_name must not be blank")
    att.original_name = new_name
    db.commit()
    db.refresh(att)
    return _to_item(att)


@router.delete("/api/attachments/{attachment_id}", status_code=204)
def delete_attachment(
    attachment_id: int, db: Annotated[Session, Depends(get_db)]
) -> Response:
    """Owner-initiated delete: remove both the DB row and the file on disk."""
    att = _get_attachment_or_404(db, attachment_id)
    project_id, stored_name = att.project_id, att.stored_name
    db.delete(att)
    db.commit()
    storage.delete(project_id, stored_name)
    return Response(status_code=204)


@router.get("/api/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int, db: Annotated[Session, Depends(get_db)]
) -> FileResponse:
    """Stream the original file as an attachment (download), with an explicit type + nosniff.

    Starlette encodes a non-ASCII ``filename`` via RFC-5987 ``filename*`` automatically, so Arabic
    or long names are preserved safely in ``Content-Disposition``.
    """
    att = _get_attachment_or_404(db, attachment_id)
    path = storage.path_for(att.project_id, att.stored_name)
    if not path.is_file():
        raise HTTPException(404, "File not found on disk")
    return FileResponse(
        path,
        media_type=att.content_type,
        filename=att.original_name,
        content_disposition_type="attachment",
        headers=dict(NOSNIFF),
    )


@router.get("/api/attachments/{attachment_id}/preview")
def preview_attachment(
    attachment_id: int, db: Annotated[Session, Depends(get_db)]
) -> FileResponse:
    """Inline preview: PDF as ``application/pdf``, Markdown as ``text/markdown``; DOCX → 415.

    Always inline (``Content-Disposition: inline``) with ``nosniff`` so the browser renders the PDF
    viewer / text without sniffing or executing the content.
    """
    att = _get_attachment_or_404(db, attachment_id)
    if att.file_type not in _PREVIEWABLE:
        raise HTTPException(415, "No inline preview for this file type")
    path = storage.path_for(att.project_id, att.stored_name)
    if not path.is_file():
        raise HTTPException(404, "File not found on disk")
    return FileResponse(
        path,
        media_type=att.content_type,
        filename=att.original_name,
        content_disposition_type="inline",
        headers=dict(NOSNIFF),
    )
