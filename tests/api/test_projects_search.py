"""T014 — free-text search `q` over title/description/skills (Arabic + Latin)."""
from __future__ import annotations

from tests.api.conftest import make_project


def _ids(items) -> set[int]:
    return {it["id"] for it in items}


def _seed(api_env):
    with api_env.session() as s:
        arabic_title = make_project(
            s, _n=1,
            title="تطوير موقع",
            description="نص عادي",
            skills=["java"],
        )
        arabic_desc = make_project(
            s, _n=2,
            title="Website build",
            description="نحتاج خبير في الاستضافة",
            skills=["php"],
        )
        latin_skill = make_project(
            s, _n=3,
            title="Mobile app",
            description="generic description",
            skills=["python", "تصميم"],
        )
        unrelated = make_project(
            s, _n=4,
            title="حملة تسويقية",
            description="إدارة محتوى",
            skills=["seo"],
        )
        s.commit()
        return {
            "arabic_title": arabic_title.id,
            "arabic_desc": arabic_desc.id,
            "latin_skill": latin_skill.id,
            "unrelated": unrelated.id,
        }


def test_q_matches_arabic_substring_in_title(api_env):
    ids = _seed(api_env)
    client = api_env.client(auth_enabled=False)
    items = client.get("/api/projects", params={"q": "تطوير"}).json()["items"]
    assert ids["arabic_title"] in _ids(items)
    assert ids["unrelated"] not in _ids(items)


def test_q_matches_arabic_substring_in_description(api_env):
    ids = _seed(api_env)
    client = api_env.client(auth_enabled=False)
    items = client.get("/api/projects", params={"q": "الاستضافة"}).json()["items"]
    assert ids["arabic_desc"] in _ids(items)
    assert ids["unrelated"] not in _ids(items)


def test_q_matches_latin_substring_in_skills(api_env):
    ids = _seed(api_env)
    client = api_env.client(auth_enabled=False)
    items = client.get("/api/projects", params={"q": "python"}).json()["items"]
    assert ids["latin_skill"] in _ids(items)
    assert ids["unrelated"] not in _ids(items)


def test_q_excludes_projects_without_the_term(api_env):
    ids = _seed(api_env)
    client = api_env.client(auth_enabled=False)
    items = client.get("/api/projects", params={"q": "تطوير"}).json()["items"]
    # Only the project whose title contains the term matches.
    assert _ids(items) == {ids["arabic_title"]}
