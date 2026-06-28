"""Filesystem storage for uploaded attachments (Feature 3, US2).

Security-critical (constitution IX). Every upload is validated by **extension + magic bytes + size**
*before* anything is written to disk; the on-disk name is a server-generated UUID, so no
user-controlled input ever reaches a filesystem path — no traversal, no collision. Bytes live under
``attachments_dir`` (resolved from secrets at call time, so the per-test env var is honoured),
outside any public web path, and are only ever served through the gated streaming endpoints with an
explicit content-type + ``nosniff`` — never via a static mount, never executed.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from ..config.secrets import get_secrets

# file_type -> MIME used when the bytes are streamed back. The stored content-type is derived from
# the *validated* type, never trusted from the client's declared header.
_CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/markdown",
}


class StorageError(Exception):
    """Base for upload-validation failures (the router maps each subtype to an HTTP status)."""


class UnsupportedTypeError(StorageError):
    """Extension not allowed, or the real bytes don't match the claimed type → HTTP 400."""


class FileTooLargeError(StorageError):
    """Payload exceeds ``upload_max_bytes`` → HTTP 413."""


def content_type_for(file_type: str) -> str:
    """Safe MIME for a validated file type (``pdf``/``docx``/``md``)."""
    return _CONTENT_TYPES[file_type]


def _ext_of(filename: str) -> str:
    """Lowercased extension (no leading dot) taken from the *original* filename; ``""`` if none."""
    return Path(filename).suffix.lower().lstrip(".")


def _magic_ok(file_type: str, data: bytes) -> bool:
    """Confirm the real bytes match the claimed type — defeats a renamed-extension upload."""
    if file_type == "pdf":
        return data.startswith(b"%PDF-")
    if file_type == "docx":
        # OOXML (.docx) is a ZIP container; check the ZIP local-file-header magic.
        return data.startswith(b"PK\x03\x04")
    if file_type == "md":
        # Markdown is plain text: it must decode as UTF-8 (a binary blob named .md is rejected).
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    return False


def validate(
    filename: str,
    content_type: str | None,
    data: bytes,
    *,
    allowed_types: list[str],
    max_bytes: int,
) -> tuple[str, str]:
    """Validate an upload and return ``(file_type, content_type)`` or raise a typed error.

    Checks, **in order**: (a) the lowercased extension of ``filename`` is in ``allowed_types``;
    (b) the magic bytes confirm the real type; (c) ``len(data) <= max_bytes``. The client-declared
    ``content_type`` is advisory only — the returned content-type is derived from the validated
    type. Nothing is written here; the caller persists only after a clean return.
    """
    file_type = _ext_of(filename)
    if file_type not in _CONTENT_TYPES or file_type not in allowed_types:
        raise UnsupportedTypeError(
            f"Unsupported file type '{file_type or filename}'. "
            f"Allowed types: {', '.join(allowed_types)}."
        )
    if not _magic_ok(file_type, data):
        raise UnsupportedTypeError(
            f"File contents do not match a valid {file_type.upper()} file."
        )
    if len(data) > max_bytes:
        raise FileTooLargeError(
            f"File is too large ({len(data)} bytes); the maximum is {max_bytes} bytes."
        )
    return file_type, content_type_for(file_type)


def _root() -> Path:
    """Storage root, resolved from secrets at call time (honours the per-test ATTACHMENTS_DIR)."""
    return Path(get_secrets().attachments_dir)


def _project_dir(project_id: int) -> Path:
    return _root() / str(project_id)


def path_for(project_id: int, stored_name: str) -> Path:
    """On-disk path for a stored file: ``{attachments_dir}/{project_id}/{stored_name}``."""
    return _project_dir(project_id) / stored_name


def save(project_id: int, file_type: str, data: bytes) -> str:
    """Write ``data`` under a server-generated ``{uuid}.{file_type}`` name; return that name.

    The stored name is derived **only** from a fresh UUID and the validated type — never from the
    owner's ``original_name`` — so the path is non-traversable and collision-free by construction.
    """
    stored_name = f"{uuid4().hex}.{file_type}"
    dest = path_for(project_id, stored_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return stored_name


def read_bytes(project_id: int, stored_name: str) -> bytes:
    """Read a stored file's bytes."""
    return path_for(project_id, stored_name).read_bytes()


def open_stream(project_id: int, stored_name: str):
    """Open a stored file for binary streaming (caller closes)."""
    return path_for(project_id, stored_name).open("rb")


def delete(project_id: int, stored_name: str) -> None:
    """Remove a stored file; tolerate an already-missing file (idempotent owner-initiated delete)."""
    try:
        path_for(project_id, stored_name).unlink()
    except FileNotFoundError:
        pass
