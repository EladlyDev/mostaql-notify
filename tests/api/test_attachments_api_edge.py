"""Attachment API EDGE / security tests (Feature 3, US2).

Companion to ``test_attachments_api.py`` — these target the corners the main suite leaves uncovered:
the ``GET /api/upload-config`` endpoint, the exact size boundary (max / max+1), the capped-read
guard against an oversize buffer, 0-byte and invalid-UTF-8 markdown, uppercase extensions,
content-type spoofing (client header is never trusted), a narrowed allow-list, the
file-missing-on-disk 404s for download/preview, rename whitespace handling, and delete idempotency.
"""
from __future__ import annotations

import io
import json
import re
import zipfile

from mostaql_notifier.db.models import Attachment, Setting
from tests.api.conftest import make_project

STORED_RE = re.compile(r"^[0-9a-f]{32}\.(pdf|docx|md)$")


# --- builders ----------------------------------------------------------------------------------

def _pdf(size: int | None = None) -> bytes:
    """A magic-valid PDF. With ``size`` set, returns exactly ``size`` bytes (``%PDF-`` + filler)."""
    if size is None:
        return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    assert size >= 5
    return b"%PDF-" + b"0" * (size - 5)


def _docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
    return buf.getvalue()


def _files_under(path) -> list:
    return [p for p in path.rglob("*") if p.is_file()] if path.exists() else []


def _new_project(api_env) -> int:
    with api_env.session() as s:
        p = make_project(s)
        s.commit()
        return p.id


def _attachment_count(api_env, project_id: int) -> int:
    with api_env.session() as s:
        return s.query(Attachment).filter(Attachment.project_id == project_id).count()


def _set_int(api_env, key: str, value: int) -> None:
    with api_env.session() as s:
        s.get(Setting, key).value = str(value)
        s.commit()


def _set_json(api_env, key: str, value) -> None:
    with api_env.session() as s:
        s.get(Setting, key).value = json.dumps(value)
        s.commit()


# --- GET /api/upload-config --------------------------------------------------------------------

def test_upload_config_returns_seeded_defaults(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.get("/api/upload-config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed_types"] == ["pdf", "docx", "md"]
    assert body["max_bytes"] == 10485760  # 10 MiB default


def test_upload_config_reflects_retuned_settings(api_env):
    _set_int(api_env, "upload_max_bytes", 2048)
    _set_json(api_env, "upload_allowed_types", ["pdf"])
    client = api_env.client(auth_enabled=False)
    body = client.get("/api/upload-config").json()
    assert body["allowed_types"] == ["pdf"]
    assert body["max_bytes"] == 2048


def test_upload_config_requires_auth_when_enabled(api_env):
    anon = api_env.client(auth_enabled=True, password="pw")
    assert anon.get("/api/upload-config").status_code == 401
    # Logging in unlocks it.
    anon.post("/api/auth/login", json={"password": "pw"})
    assert anon.get("/api/upload-config").status_code == 200


# --- size boundary (max / max+1) + capped read -------------------------------------------------

def test_pdf_exactly_max_bytes_is_accepted(api_env):
    pid = _new_project(api_env)
    _set_int(api_env, "upload_max_bytes", 64)  # tiny cap → cheap boundary
    client = api_env.client(auth_enabled=False)

    data = _pdf(64)
    assert len(data) == 64
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("exact.pdf", data, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["size_bytes"] == 64
    assert len(_files_under(api_env.attachments_dir / str(pid))) == 1


def test_pdf_one_over_max_bytes_is_rejected_nothing_stored(api_env):
    pid = _new_project(api_env)
    _set_int(api_env, "upload_max_bytes", 64)
    client = api_env.client(auth_enabled=False)

    data = _pdf(65)
    assert len(data) == 65
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("over.pdf", data, "application/pdf")},
    )
    assert resp.status_code == 413, resp.text
    assert "detail" in resp.json()
    assert _files_under(api_env.attachments_dir / str(pid)) == []
    assert _attachment_count(api_env, pid) == 0


def test_capped_read_never_buffers_a_far_oversize_payload(api_env):
    # With a tiny cap, a payload orders of magnitude larger still 413s and stores nothing — the
    # router only ever reads max_bytes+1 bytes, so the oversize body is never fully buffered.
    pid = _new_project(api_env)
    _set_int(api_env, "upload_max_bytes", 16)
    client = api_env.client(auth_enabled=False)

    huge = _pdf(1_000_000)  # ~1 MB, cap is 16
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("huge.pdf", huge, "application/pdf")},
    )
    assert resp.status_code == 413
    assert _files_under(api_env.attachments_dir / str(pid)) == []
    assert _attachment_count(api_env, pid) == 0


# --- markdown corner cases ---------------------------------------------------------------------

def test_zero_byte_md_is_accepted_and_stored(api_env):
    # CURRENT BEHAVIOUR: an empty .md passes the UTF-8 magic gate (b"" decodes) and 0 <= max, so it
    # is stored with size_bytes == 0. Judgement: not flagged as a strict bug — there is no minimum
    # -size requirement and an empty markdown file is valid plain text. Documented as accepted.
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("empty.md", b"", "text/markdown")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["size_bytes"] == 0
    assert resp.json()["file_type"] == "md"
    stored = _files_under(api_env.attachments_dir / str(pid))
    assert len(stored) == 1
    assert stored[0].stat().st_size == 0


def test_md_with_invalid_utf8_rejected_nothing_stored(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("bad.md", b"\xff\xfe\x00\x01", "text/markdown")},
    )
    assert resp.status_code == 400
    assert "detail" in resp.json()
    assert _files_under(api_env.attachments_dir / str(pid)) == []
    assert _attachment_count(api_env, pid) == 0


# --- extension casing --------------------------------------------------------------------------

def test_uppercase_extension_stored_lowercase(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("FILE.PDF", _pdf(), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["file_type"] == "pdf"  # normalised lowercase
    assert body["original_name"] == "FILE.PDF"  # display name kept verbatim
    stored = _files_under(api_env.attachments_dir / str(pid))
    assert len(stored) == 1
    assert STORED_RE.match(stored[0].name)  # ...{uuid}.pdf, lowercased ext


# --- content-type is server-derived, never trusted from the client -----------------------------

def test_content_type_spoof_png_header_still_pdf(api_env):
    # Valid PDF bytes uploaded with a lying multipart content-type "image/png": the server validates
    # by MAGIC, accepts it (201), and the stored + served content-type is the safe server-derived
    # application/pdf — the client's declared type is discarded.
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("real.pdf", _pdf(), "image/png")},  # spoofed content-type
    )
    assert resp.status_code == 201, resp.text
    aid = resp.json()["id"]

    with api_env.session() as s:
        row = s.get(Attachment, aid)
        assert row.content_type == "application/pdf"  # NOT image/png
        assert row.file_type == "pdf"

    dl = client.get(f"/api/attachments/{aid}/download")
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("application/pdf")
    assert dl.headers["x-content-type-options"] == "nosniff"
    assert dl.headers["content-disposition"].startswith("attachment")


def test_png_filename_rejected_even_with_pdf_bytes(api_env):
    # Reverse of the spoof: a .png extension is not in the allow-list → 400, regardless of bytes.
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("shot.png", _pdf(), "application/pdf")},
    )
    assert resp.status_code == 400
    assert _files_under(api_env.attachments_dir / str(pid)) == []
    assert _attachment_count(api_env, pid) == 0


# --- narrowed allow-list -----------------------------------------------------------------------

def test_narrowed_allowed_types_rejects_docx(api_env):
    pid = _new_project(api_env)
    _set_json(api_env, "upload_allowed_types", ["pdf"])  # only PDFs allowed now
    client = api_env.client(auth_enabled=False)

    # A valid DOCX is now refused (type not allowed) — nothing stored.
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("proposal.docx", _docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp.status_code == 400
    assert _files_under(api_env.attachments_dir / str(pid)) == []
    assert _attachment_count(api_env, pid) == 0

    # ...and a PDF still goes through under the same narrowed config.
    ok = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("cv.pdf", _pdf(), "application/pdf")},
    )
    assert ok.status_code == 201

    # Restore the default allow-list (defensive — fixtures are per-test, but keep it explicit).
    _set_json(api_env, "upload_allowed_types", ["pdf", "docx", "md"])


# --- file removed from disk: download / preview both 404 (row still present) -------------------

def _upload_pdf_then_unlink_disk(api_env, client, pid: int) -> int:
    aid = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("doc.pdf", _pdf(), "application/pdf")},
    ).json()["id"]
    on_disk = list((api_env.attachments_dir / str(pid)).glob("*"))
    assert len(on_disk) == 1
    on_disk[0].unlink()  # remove the file, keep the DB row
    return aid


def test_download_404_when_file_missing_on_disk(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = _upload_pdf_then_unlink_disk(api_env, client, pid)

    resp = client.get(f"/api/attachments/{aid}/download")
    assert resp.status_code == 404
    assert "detail" in resp.json()
    # The row is untouched — only the bytes are gone.
    assert _attachment_count(api_env, pid) == 1


def test_preview_404_when_file_missing_on_disk(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = _upload_pdf_then_unlink_disk(api_env, client, pid)

    resp = client.get(f"/api/attachments/{aid}/preview")
    assert resp.status_code == 404
    assert "detail" in resp.json()
    assert _attachment_count(api_env, pid) == 1


# --- preview content-disposition / type gating (consolidated, new angles) ----------------------

def test_preview_pdf_is_inline_with_nosniff(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("p.pdf", _pdf(), "application/pdf")},
    ).json()["id"]
    resp = client.get(f"/api/attachments/{aid}/preview")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("inline")
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_preview_docx_returns_415_before_touching_disk(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("p.docx", _docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    ).json()["id"]
    resp = client.get(f"/api/attachments/{aid}/preview")
    assert resp.status_code == 415


# --- rename whitespace handling ----------------------------------------------------------------

PADDED = "  ملف جديد.pdf  "


def test_rename_strips_surrounding_whitespace_in_db(api_env):
    # FIXED: rename trims the display name before storing, so surrounding whitespace never leaks
    # into the persisted original_name (validation and storage now agree on the trimmed value).
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("orig.pdf", _pdf(), "application/pdf")},
    ).json()["id"]

    resp = client.patch(f"/api/attachments/{aid}", json={"original_name": PADDED})
    assert resp.status_code == 200
    assert resp.json()["original_name"] == PADDED.strip()  # trimmed in the response
    with api_env.session() as s:
        assert s.get(Attachment, aid).original_name == PADDED.strip()  # and persisted trimmed


def test_rename_should_strip_surrounding_whitespace(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("orig.pdf", _pdf(), "application/pdf")},
    ).json()["id"]

    resp = client.patch(f"/api/attachments/{aid}", json={"original_name": PADDED})
    assert resp.status_code == 200
    assert resp.json()["original_name"] == PADDED.strip()  # stripped (fixed)


# --- delete idempotency when the on-disk file is already gone -----------------------------------

def test_delete_204_when_file_already_removed_from_disk(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = _upload_pdf_then_unlink_disk(api_env, client, pid)

    # The endpoint still succeeds even though storage.delete finds nothing to unlink.
    resp = client.delete(f"/api/attachments/{aid}")
    assert resp.status_code == 204
    assert _attachment_count(api_env, pid) == 0
    assert client.get(f"/api/projects/{pid}/attachments").json()["items"] == []


def test_storage_delete_twice_does_not_raise(api_env):
    from mostaql_notifier.storage import attachments as storage

    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    upload = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("x.pdf", _pdf(), "application/pdf")},
    ).json()
    with api_env.session() as s:
        stored_name = s.get(Attachment, upload["id"]).stored_name

    storage.delete(pid, stored_name)
    storage.delete(pid, stored_name)  # idempotent — second call is a no-op
    assert not (api_env.attachments_dir / str(pid) / stored_name).exists()


# --- multiple uploads of the same display name -> distinct uuid files, both listed -------------

def test_same_filename_twice_distinct_uuids_both_listed(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    ids = []
    for _ in range(2):
        r = client.post(
            f"/api/projects/{pid}/attachments",
            files={"file": ("same.pdf", _pdf(), "application/pdf")},
        )
        assert r.status_code == 201
        ids.append(r.json()["id"])

    stored = _files_under(api_env.attachments_dir / str(pid))
    assert len(stored) == 2
    assert len({f.name for f in stored}) == 2  # distinct server-generated names
    listed = client.get(f"/api/projects/{pid}/attachments").json()["items"]
    assert {it["id"] for it in listed} == set(ids)
    assert [it["original_name"] for it in listed] == ["same.pdf", "same.pdf"]
