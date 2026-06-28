"""Storage-layer EDGE / security tests for attachments (Feature 3, US2).

Companion to ``test_attachment_storage.py`` — these exercise the corners that the happy-path suite
leaves uncovered: the ``_magic_ok`` fall-through for an unknown file type, the binary
``open_stream`` reader, ``content_type_for`` on an unknown type, 0-byte handling, and
``delete`` idempotency when nothing was ever written. None of the existing tests are duplicated.
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
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
    return buf.getvalue()


@pytest.fixture
def attach_dir(tmp_path, monkeypatch):
    """Point the storage root at a temp dir and clear the secrets cache so it is honoured.

    Same pattern as ``test_attachment_storage.py`` — ``storage.*`` resolves ``attachments_dir``
    from secrets at call time, so the per-test env var must be set + the lru_cache cleared.
    """
    d = tmp_path / "attachments"
    monkeypatch.setenv("ATTACHMENTS_DIR", str(d))
    secrets_mod.get_secrets.cache_clear()
    yield d
    secrets_mod.get_secrets.cache_clear()


# --- _magic_ok: per-type truth table + the unknown-type fall-through (L62, 55->62) -------------

def test_magic_ok_unknown_type_returns_false():
    # A file_type the magic-table doesn't know about can never validate — defensive default.
    # (Reachable only by a direct call: validate() rejects an unknown extension before this.)
    assert storage._magic_ok("zip", b"PK\x03\x04") is False
    assert storage._magic_ok("", b"%PDF-") is False
    assert storage._magic_ok("exe", b"MZ\x90\x00") is False


def test_magic_ok_pdf_truth_table():
    assert storage._magic_ok("pdf", b"%PDF-1.7\n...") is True
    assert storage._magic_ok("pdf", b"%PDF-") is True
    # Right type word, wrong bytes (e.g. a JPEG renamed .pdf) → rejected.
    assert storage._magic_ok("pdf", b"\xff\xd8\xff\xe0") is False
    assert storage._magic_ok("pdf", b"") is False


def test_magic_ok_docx_truth_table():
    assert storage._magic_ok("docx", b"PK\x03\x04rest") is True
    # A different ZIP variant marker (empty/central-dir-only) is NOT a local-file header.
    assert storage._magic_ok("docx", b"PK\x05\x06") is False
    assert storage._magic_ok("docx", b"not-a-zip") is False


def test_magic_ok_md_truth_table():
    assert storage._magic_ok("md", "نص بالعربية".encode()) is True
    # Empty bytes decode cleanly as UTF-8 → markdown gate passes (see 0-byte behaviour below).
    assert storage._magic_ok("md", b"") is True
    # Invalid UTF-8 is not text → rejected.
    assert storage._magic_ok("md", b"\xff\xfe\x00\x01") is False


# --- 0-byte handling at the storage layer ------------------------------------------------------

def test_empty_md_validates_and_roundtrips(attach_dir):
    # An empty .md passes the magic gate (empty decodes as UTF-8) and is within any non-negative
    # size cap, so validate() accepts it. Documents the 0-byte acceptance at the storage layer.
    file_type, ctype = storage.validate(
        "empty.md", "text/markdown", b"", allowed_types=ALLOWED, max_bytes=MAX
    )
    assert (file_type, ctype) == ("md", "text/markdown")
    stored = storage.save(11, "md", b"")
    assert storage.read_bytes(11, stored) == b""
    assert storage.path_for(11, stored).stat().st_size == 0


# --- open_stream: binary reader (L131) ---------------------------------------------------------

def test_open_stream_reads_then_closes(attach_dir):
    data = _minimal_pdf()
    stored = storage.save(5, "pdf", data)

    f = storage.open_stream(5, stored)
    try:
        assert f.read() == data
        assert "b" in f.mode  # opened in binary mode
    finally:
        f.close()
    assert f.closed


def test_open_stream_usable_as_context_manager(attach_dir):
    data = _minimal_docx()
    stored = storage.save(6, "docx", data)
    with storage.open_stream(6, stored) as f:
        assert f.read() == data
    assert f.closed


# --- content_type_for: unknown type is a hard KeyError (no silent default) ----------------------

def test_content_type_for_unknown_type_raises():
    with pytest.raises(KeyError):
        storage.content_type_for("zip")


# --- delete idempotency: tolerate an already-missing file / never-created dir -------------------

def test_delete_is_noop_when_file_never_existed(attach_dir):
    # No project dir, no file — delete must be a harmless no-op (idempotent owner delete).
    storage.delete(404, "deadbeefdeadbeefdeadbeefdeadbeef.pdf")
    storage.delete(404, "deadbeefdeadbeefdeadbeefdeadbeef.pdf")  # twice → still no raise


def test_delete_twice_after_save(attach_dir):
    stored = storage.save(8, "pdf", _minimal_pdf())
    assert storage.path_for(8, stored).exists()
    storage.delete(8, stored)
    assert not storage.path_for(8, stored).exists()
    storage.delete(8, stored)  # second delete on the now-missing file is harmless


# --- path_for: server-generated name is non-traversable by construction ------------------------

def test_path_for_stays_under_project_dir(attach_dir):
    stored = storage.save(9, "pdf", _minimal_pdf())
    assert STORED_RE.match(stored)
    path = storage.path_for(9, stored).resolve()
    assert path.parent == (attach_dir / "9").resolve()
    assert ".." not in stored
