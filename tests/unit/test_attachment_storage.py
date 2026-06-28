"""Storage-layer validation + safe-naming tests (Feature 3, US2 — T026).

Covers: valid pdf/docx/md pass; a disallowed extension is rejected; a magic-byte mismatch (a renamed
extension, e.g. a JPEG named ``.pdf``) is rejected; an oversize payload is rejected; the stored name
is a server-generated ``{uuid}.{ext}`` living under ``{attachments_dir}/{project_id}/``; and the
owner's ``original_name`` is **never** used to build the on-disk path (no traversal).
"""
from __future__ import annotations

import io
import re
import zipfile

import pytest

from mostaql_notifier.config import secrets as secrets_mod
from mostaql_notifier.storage import attachments as storage

ALLOWED = ["pdf", "docx", "md"]
MAX = 10 * 1024 * 1024

STORED_RE = re.compile(r"^[0-9a-f]{32}\.(pdf|docx|md)$")


def _minimal_pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n"


def _minimal_docx() -> bytes:
    """A real 1-entry ZIP — starts with the OOXML/ZIP magic ``PK\\x03\\x04``."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
    return buf.getvalue()


def _minimal_md() -> bytes:
    return "# عنوان\nنص بالعربية\n".encode()


@pytest.fixture
def attach_dir(tmp_path, monkeypatch):
    """Point the storage root at a temp dir and clear the secrets cache so it is honoured."""
    d = tmp_path / "attachments"
    monkeypatch.setenv("ATTACHMENTS_DIR", str(d))
    secrets_mod.get_secrets.cache_clear()
    yield d
    secrets_mod.get_secrets.cache_clear()


# --- validate() -------------------------------------------------------------

def test_valid_pdf_passes():
    assert storage.validate("cv.pdf", "application/pdf", _minimal_pdf(),
                            allowed_types=ALLOWED, max_bytes=MAX) == ("pdf", "application/pdf")


def test_valid_docx_passes():
    file_type, ctype = storage.validate(
        "proposal.docx", None, _minimal_docx(), allowed_types=ALLOWED, max_bytes=MAX
    )
    assert file_type == "docx"
    assert ctype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_valid_md_passes():
    assert storage.validate("notes.MD", "text/markdown", _minimal_md(),
                            allowed_types=ALLOWED, max_bytes=MAX) == ("md", "text/markdown")


def test_extension_not_allowed_is_rejected():
    with pytest.raises(storage.UnsupportedTypeError):
        storage.validate("photo.jpg", "image/jpeg", b"\xff\xd8\xff\xe0",
                        allowed_types=ALLOWED, max_bytes=MAX)


def test_no_extension_is_rejected():
    with pytest.raises(storage.UnsupportedTypeError):
        storage.validate("README", None, _minimal_md(), allowed_types=ALLOWED, max_bytes=MAX)


def test_renamed_extension_fails_magic_check():
    # A JPEG (FF D8 FF) renamed to .pdf must fail the magic-byte gate.
    with pytest.raises(storage.UnsupportedTypeError):
        storage.validate("evil.pdf", "application/pdf", b"\xff\xd8\xff\xe0\x00\x10",
                        allowed_types=ALLOWED, max_bytes=MAX)


def test_binary_named_md_fails_magic_check():
    # Invalid UTF-8 bytes named .md are not markdown.
    with pytest.raises(storage.UnsupportedTypeError):
        storage.validate("x.md", "text/markdown", b"\xff\xfe\x00\x01\x80",
                        allowed_types=ALLOWED, max_bytes=MAX)


def test_oversize_is_rejected():
    big = b"%PDF-1.4\n" + b"0" * 100
    with pytest.raises(storage.FileTooLargeError):
        storage.validate("big.pdf", "application/pdf", big, allowed_types=ALLOWED, max_bytes=50)


def test_extension_checked_before_magic_and_size():
    # An oversize JPEG named .jpg fails on the (first) extension check, not size/magic.
    with pytest.raises(storage.UnsupportedTypeError):
        storage.validate("big.jpg", "image/jpeg", b"\xff\xd8\xff" + b"0" * 100,
                        allowed_types=ALLOWED, max_bytes=10)


def test_content_type_for_mapping():
    assert storage.content_type_for("pdf") == "application/pdf"
    assert storage.content_type_for("md") == "text/markdown"
    assert storage.content_type_for("docx").endswith("wordprocessingml.document")


# --- save() / path_for() / delete() -----------------------------------------

def test_save_generates_uuid_name_under_project_dir(attach_dir):
    file_type, _ = storage.validate(
        "cv.pdf", "application/pdf", _minimal_pdf(), allowed_types=ALLOWED, max_bytes=MAX
    )
    stored = storage.save(7, file_type, _minimal_pdf())
    assert STORED_RE.match(stored), stored

    path = storage.path_for(7, stored)
    assert path.exists()
    # The file sits exactly under {attachments_dir}/{project_id}/.
    assert path.parent == attach_dir / "7"
    assert path.read_bytes() == _minimal_pdf()


def test_stored_name_never_derived_from_original_name(attach_dir):
    # save() does not even accept original_name — a traversal-y display name cannot influence the
    # path. Confirm the resulting file stays strictly inside the project dir.
    stored = storage.save(3, "pdf", _minimal_pdf())
    path = storage.path_for(3, stored).resolve()
    project_dir = (attach_dir / "3").resolve()
    assert str(path).startswith(str(project_dir))
    assert path.parent == project_dir
    # Nothing escaped the attachments root.
    assert "etc" not in str(path)
    assert ".." not in stored


def test_save_then_delete_removes_file(attach_dir):
    stored = storage.save(1, "md", _minimal_md())
    path = storage.path_for(1, stored)
    assert path.exists()
    storage.delete(1, stored)
    assert not path.exists()
    # delete is idempotent — a second call on a missing file is harmless.
    storage.delete(1, stored)


def test_read_bytes_roundtrip(attach_dir):
    stored = storage.save(2, "docx", _minimal_docx())
    assert storage.read_bytes(2, stored) == _minimal_docx()
