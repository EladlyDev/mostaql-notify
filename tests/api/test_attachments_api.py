"""Attachment API tests (Feature 3, US2 — T025, security-critical).

Covers: valid PDF/DOCX/MD upload stored + listed with metadata; unsupported type → 400 (nothing
stored); oversize → 413 (nothing stored); magic-byte mismatch (renamed extension) → rejected;
duplicate / very-long / Arabic / unsafe-character filenames safe-stored with ``original_name``
retained and no traversal; download/preview/rename/delete require auth; delete removes both the row
and the file; DOCX preview → 415.
"""
from __future__ import annotations

import io
import re
import zipfile

from mostaql_notifier.db.models import Attachment, Setting
from tests.api.conftest import make_project

STORED_RE = re.compile(r"^[0-9a-f]{32}\.(pdf|docx|md)$")


def _pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types/>")
    return buf.getvalue()


def _md() -> bytes:
    return "# عنوان\n".encode()


def _files_under(path) -> list:
    return [p for p in path.rglob("*") if p.is_file()] if path.exists() else []


def _new_project(api_env) -> int:
    with api_env.session() as s:
        p = make_project(s)
        s.commit()
        return p.id


def _attachment_count(api_env, project_id: int) -> int:
    with api_env.session() as s:
        return (
            s.query(Attachment).filter(Attachment.project_id == project_id).count()
        )


# --- happy-path upload / list ----------------------------------------------

def test_upload_pdf_docx_md_stored_and_listed(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)

    cases = [
        ("cv.pdf", _pdf(), "application/pdf", "pdf", True),
        ("proposal.docx", _docx(),
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx", False),
        ("notes.md", _md(), "text/markdown", "md", True),
    ]
    created_ids = []
    for name, data, ctype, ftype, can_prev in cases:
        resp = client.post(
            f"/api/projects/{pid}/attachments",
            files={"file": (name, data, ctype)},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["original_name"] == name
        assert body["file_type"] == ftype
        assert body["size_bytes"] == len(data)
        assert body["can_preview"] is can_prev
        assert body["project_id"] == pid
        assert "uploaded_at" in body
        created_ids.append(body["id"])

    # All three are listed with metadata.
    listed = client.get(f"/api/projects/{pid}/attachments").json()["items"]
    assert {it["id"] for it in listed} == set(created_ids)
    assert {it["file_type"] for it in listed} == {"pdf", "docx", "md"}

    # Each stored file uses a safe uuid name under {attachments_dir}/{project_id}/.
    proj_dir = api_env.attachments_dir / str(pid)
    stored = _files_under(proj_dir)
    assert len(stored) == 3
    for f in stored:
        assert STORED_RE.match(f.name), f.name
        assert f.parent == proj_dir


def test_upload_for_missing_project_404(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.post(
        "/api/projects/999999/attachments",
        files={"file": ("cv.pdf", _pdf(), "application/pdf")},
    )
    assert resp.status_code == 404


def test_list_for_missing_project_404(api_env):
    client = api_env.client(auth_enabled=False)
    assert client.get("/api/projects/999999/attachments").status_code == 404


# --- rejections (nothing stored) -------------------------------------------

def test_unsupported_type_400_nothing_stored(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0jpeg-bytes", "image/jpeg")},
    )
    assert resp.status_code == 400
    assert "detail" in resp.json()
    assert _files_under(api_env.attachments_dir / str(pid)) == []
    assert _attachment_count(api_env, pid) == 0


def test_renamed_extension_rejected_nothing_stored(api_env):
    # A JPEG renamed to .pdf must fail the magic-byte check (→ 400), and store nothing.
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("evil.pdf", b"\xff\xd8\xff\xe0not-a-pdf", "application/pdf")},
    )
    assert resp.status_code == 400
    assert _files_under(api_env.attachments_dir / str(pid)) == []
    assert _attachment_count(api_env, pid) == 0


def test_oversize_413_nothing_stored(api_env):
    pid = _new_project(api_env)
    # Shrink the cap so a tiny valid PDF trips it (keeps the test fast).
    with api_env.session() as s:
        s.get(Setting, "upload_max_bytes").value = "16"
        s.commit()

    client = api_env.client(auth_enabled=False)
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("big.pdf", _pdf(), "application/pdf")},  # > 16 bytes
    )
    assert resp.status_code == 413
    assert "detail" in resp.json()
    assert _files_under(api_env.attachments_dir / str(pid)) == []
    assert _attachment_count(api_env, pid) == 0


# --- safe storage of awkward filenames -------------------------------------

def test_duplicate_filenames_both_stored_distinctly(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    for _ in range(2):
        r = client.post(
            f"/api/projects/{pid}/attachments",
            files={"file": ("same.pdf", _pdf(), "application/pdf")},
        )
        assert r.status_code == 201

    assert _attachment_count(api_env, pid) == 2
    stored = _files_under(api_env.attachments_dir / str(pid))
    assert len(stored) == 2
    # Distinct server-generated names, same display name retained.
    assert len({f.name for f in stored}) == 2
    items = client.get(f"/api/projects/{pid}/attachments").json()["items"]
    assert [it["original_name"] for it in items] == ["same.pdf", "same.pdf"]


def test_long_and_arabic_filename_retained(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    long_name = "تقرير_" + "ط" * 250 + ".pdf"
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": (long_name, _pdf(), "application/pdf")},
    )
    assert resp.status_code == 201
    assert resp.json()["original_name"] == long_name
    # Stored on disk under a short, safe uuid name regardless of the long display name.
    stored = _files_under(api_env.attachments_dir / str(pid))
    assert len(stored) == 1
    assert STORED_RE.match(stored[0].name)


def test_unsafe_traversal_filename_stays_inside_project_dir(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    resp = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("../../etc/passwd.pdf", _pdf(), "application/pdf")},
    )
    assert resp.status_code == 201

    attach_root = api_env.attachments_dir.resolve()
    proj_dir = (api_env.attachments_dir / str(pid)).resolve()

    with api_env.session() as s:
        row = s.query(Attachment).filter(Attachment.project_id == pid).one()
        # Stored name is a safe uuid; original (traversal-y) name is retained verbatim for display.
        assert STORED_RE.match(row.stored_name), row.stored_name
        assert row.original_name == "../../etc/passwd.pdf"
        from mostaql_notifier.storage import attachments as storage
        on_disk = storage.path_for(pid, row.stored_name).resolve()

    # The file lives strictly inside the project dir — nothing escaped the attachments root.
    assert on_disk.parent == proj_dir
    assert str(on_disk).startswith(str(attach_root))
    # No file leaked outside the attachments root (e.g. a sibling "etc/passwd").
    assert not (attach_root.parent / "etc" / "passwd").exists()


# --- rename -----------------------------------------------------------------

def test_rename_changes_display_name_only(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("orig.pdf", _pdf(), "application/pdf")},
    ).json()["id"]

    with api_env.session() as s:
        before = s.get(Attachment, aid).stored_name

    resp = client.patch(f"/api/attachments/{aid}", json={"original_name": "renamed.pdf"})
    assert resp.status_code == 200
    assert resp.json()["original_name"] == "renamed.pdf"

    # The stored file name is untouched by a display rename.
    with api_env.session() as s:
        after = s.get(Attachment, aid)
        assert after.stored_name == before
        assert after.original_name == "renamed.pdf"


def test_rename_blank_returns_422(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("orig.pdf", _pdf(), "application/pdf")},
    ).json()["id"]

    resp = client.patch(f"/api/attachments/{aid}", json={"original_name": "   "})
    assert resp.status_code == 422


def test_rename_missing_attachment_404(api_env):
    client = api_env.client(auth_enabled=False)
    assert client.patch("/api/attachments/999999", json={"original_name": "x.pdf"}).status_code == 404


# --- download / preview -----------------------------------------------------

def test_download_streams_with_nosniff_and_attachment_disposition(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("ملف عربي.pdf", _pdf(), "application/pdf")},
    ).json()["id"]

    resp = client.get(f"/api/attachments/{aid}/download")
    assert resp.status_code == 200
    assert resp.content == _pdf()
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["content-type"].startswith("application/pdf")
    cd = resp.headers["content-disposition"]
    assert cd.startswith("attachment")
    # Arabic name is encoded via RFC-5987 filename* (not a raw non-ASCII filename=).
    assert "filename*" in cd


def test_preview_pdf_inline(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("doc.pdf", _pdf(), "application/pdf")},
    ).json()["id"]

    resp = client.get(f"/api/attachments/{aid}/preview")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.headers["content-disposition"].startswith("inline")
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_preview_markdown_as_text_markdown(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("notes.md", _md(), "text/markdown")},
    ).json()["id"]

    resp = client.get(f"/api/attachments/{aid}/preview")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.content == _md()


def test_preview_docx_returns_415(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    aid = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("p.docx", _docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    ).json()["id"]

    resp = client.get(f"/api/attachments/{aid}/preview")
    assert resp.status_code == 415
    assert "detail" in resp.json()


def test_download_missing_attachment_404(api_env):
    client = api_env.client(auth_enabled=False)
    assert client.get("/api/attachments/999999/download").status_code == 404
    assert client.get("/api/attachments/999999/preview").status_code == 404


# --- delete (row + file) ----------------------------------------------------

def test_delete_removes_row_and_file(api_env):
    pid = _new_project(api_env)
    client = api_env.client(auth_enabled=False)
    upload = client.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("gone.pdf", _pdf(), "application/pdf")},
    ).json()
    aid = upload["id"]

    proj_dir = api_env.attachments_dir / str(pid)
    assert len(_files_under(proj_dir)) == 1

    resp = client.delete(f"/api/attachments/{aid}")
    assert resp.status_code == 204
    assert _attachment_count(api_env, pid) == 0
    assert _files_under(proj_dir) == []
    # The attachment is gone from the listing.
    assert client.get(f"/api/projects/{pid}/attachments").json()["items"] == []


def test_delete_missing_attachment_404(api_env):
    client = api_env.client(auth_enabled=False)
    assert client.delete("/api/attachments/999999").status_code == 404


# --- auth gate (401 when enabled + not logged in) --------------------------

def test_endpoints_require_auth_when_enabled(api_env):
    # Seed a real attachment so the 401 isn't masked by a 404.
    with api_env.session() as s:
        p = make_project(s)
        s.commit()
        pid = p.id

    authed = api_env.client(auth_enabled=True, password="pw")
    authed.post("/api/auth/login", json={"password": "pw"})
    aid = authed.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("a.pdf", _pdf(), "application/pdf")},
    ).json()["id"]

    # A fresh client that never logged in must be rejected on every route.
    anon = api_env.client(auth_enabled=True, password="pw")
    assert anon.get(f"/api/projects/{pid}/attachments").status_code == 401
    assert anon.post(
        f"/api/projects/{pid}/attachments",
        files={"file": ("a.pdf", _pdf(), "application/pdf")},
    ).status_code == 401
    assert anon.patch(f"/api/attachments/{aid}", json={"original_name": "x.pdf"}).status_code == 401
    assert anon.delete(f"/api/attachments/{aid}").status_code == 401
    assert anon.get(f"/api/attachments/{aid}/download").status_code == 401
    assert anon.get(f"/api/attachments/{aid}/preview").status_code == 401
