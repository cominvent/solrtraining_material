"""Tests for the material renderer's routing and access rules.

Runs without a Frappe installation: a stub `frappe` module is injected before
import, so the access logic can be verified on a laptop (and in CI) rather than
only on a live site.

    python3 -m pytest tests/ -q      (or: python3 tests/test_renderer.py)
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

# ── stub frappe ───────────────────────────────────────────────────────────
frappe = types.ModuleType("frappe")
frappe.session = types.SimpleNamespace(user="Guest")
frappe._site_path = ""
frappe._roles: list[str] = []
frappe._enrollments: list[dict] = []
frappe._batch_enrollments: list[str] = []
frappe._batch_courses: list[dict] = []


def get_site_path(*parts):
    return str(Path(frappe._site_path).joinpath(*parts))


def get_roles():
    return frappe._roles


class _DB:
    def exists(self, doctype, filters):
        if doctype == "LMS Enrollment":
            return any(e["member"] == filters["member"] and e["course"] == filters["course"]
                       for e in frappe._enrollments)
        if doctype == "Batch Course":
            batches = filters["parent"][1]
            return any(bc["parent"] in batches and bc["course"] == filters["course"]
                       for bc in frappe._batch_courses)
        return False


def get_all(doctype, filters=None, pluck=None):
    if doctype == "LMS Batch Enrollment":
        return list(frappe._batch_enrollments)
    return []


frappe.get_site_path = get_site_path
frappe.get_roles = get_roles
frappe.db = _DB()
frappe.get_all = get_all
frappe.log_error = lambda *a, **k: None
frappe.utils = types.SimpleNamespace(
    get_url=lambda p: "https://lms.example.com" + p,
    quote=lambda s: s.replace(":", "%3A").replace("/", "%2F"),
    escape_html=lambda s: s,
)
sys.modules["frappe"] = frappe

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from solrtraining_material import renderer  # noqa: E402


# ── fixtures ──────────────────────────────────────────────────────────────
def setup_site(tmp: Path, manifest: dict | None = None) -> None:
    chapter = tmp / "private" / "material" / "cloud-architecture"
    chapter.mkdir(parents=True, exist_ok=True)
    (chapter / "index.html").write_text("<h1>deck</h1>")
    (chapter / "app.js").write_text("console.log(1)")
    (chapter / "lab.html").write_text("<h1>lab</h1>")
    (tmp / "private" / "secret.txt").write_text("not course material")
    if manifest is not None:
        (tmp / "private" / "material" / "material.json").write_text(json.dumps(manifest))
    frappe._site_path = str(tmp)
    frappe._roles = []
    frappe._enrollments = []
    frappe._batch_enrollments = []
    frappe._batch_courses = []


def render(path: str):
    return renderer.MaterialRenderer(path).render()


# ── tests ─────────────────────────────────────────────────────────────────
def test_can_render_only_material_paths():
    r = renderer.MaterialRenderer
    assert r("material/cloud-architecture/index.html").can_render()
    assert r("material").can_render()
    assert not r("courses/solr-cloud-architecture").can_render()
    assert not r("").can_render()
    assert not r("materialise/x").can_render()


def test_guest_is_redirected_to_login(tmp_path):
    setup_site(tmp_path, {"cloud-architecture": {"course": "solr-cloud-architecture"}})
    frappe.session.user = "Guest"
    res = render("material/cloud-architecture/index.html")
    assert res.status_code == 302
    assert "/login?redirect-to=" in res.headers["Location"]


def test_enrolled_student_gets_the_material(tmp_path):
    setup_site(tmp_path, {"cloud-architecture": {"course": "solr-cloud-architecture"}})
    frappe.session.user = "student@example.com"
    frappe._enrollments = [{"member": "student@example.com", "course": "solr-cloud-architecture"}]
    res = render("material/cloud-architecture/index.html")
    assert res.status_code == 200
    assert b"deck" in res.get_data()
    assert res.headers["Cache-Control"].startswith("private")


def test_other_course_student_is_refused(tmp_path):
    setup_site(tmp_path, {"cloud-architecture": {"course": "solr-cloud-architecture"}})
    frappe.session.user = "student@example.com"
    frappe._enrollments = [{"member": "student@example.com", "course": "solr-dense-vectors"}]
    res = render("material/cloud-architecture/index.html")
    assert res.status_code == 403


def test_classroom_batch_member_gets_access(tmp_path):
    """Jan's requirement: adding a course to a running batch grants the whole class."""
    setup_site(tmp_path, {"cloud-architecture": {"course": "solr-cloud-architecture"}})
    frappe.session.user = "student@example.com"
    frappe._batch_enrollments = ["autumn-2026-ops"]
    frappe._batch_courses = [{"parent": "autumn-2026-ops", "course": "solr-cloud-architecture"}]
    res = render("material/cloud-architecture/index.html")
    assert res.status_code == 200


def test_chapter_shared_by_two_courses(tmp_path):
    """A chapter sold standalone is also generated into the module course that
    contains it — enrollment in either one grants the material."""
    setup_site(tmp_path, {"cloud-architecture":
                          {"courses": ["solr-cloud-architecture", "solr-operations-1"]}})
    frappe.session.user = "student@example.com"
    frappe._enrollments = [{"member": "student@example.com", "course": "solr-operations-1"}]
    assert render("material/cloud-architecture/index.html").status_code == 200
    frappe._enrollments = [{"member": "student@example.com", "course": "solr-cloud-architecture"}]
    assert render("material/cloud-architecture/index.html").status_code == 200
    frappe._enrollments = [{"member": "student@example.com", "course": "solr-dense-vectors"}]
    assert render("material/cloud-architecture/index.html").status_code == 403


def test_legacy_singular_course_key_still_works(tmp_path):
    """Manifests written before chapter reuse used {"course": "..."}."""
    setup_site(tmp_path, {"cloud-architecture": {"course": "solr-cloud-architecture"}})
    frappe.session.user = "s@example.com"
    frappe._enrollments = [{"member": "s@example.com", "course": "solr-cloud-architecture"}]
    assert render("material/cloud-architecture/index.html").status_code == 200


def test_staff_bypasses_enrollment(tmp_path):
    setup_site(tmp_path, {})           # empty manifest on purpose
    frappe.session.user = "jh@cominvent.com"
    frappe._roles = ["System Manager"]
    assert render("material/cloud-architecture/index.html").status_code == 200


def test_unmapped_chapter_is_staff_only(tmp_path):
    """Fail closed: a chapter missing from material.json is never served to students."""
    setup_site(tmp_path, {})
    frappe.session.user = "student@example.com"
    frappe._enrollments = [{"member": "student@example.com", "course": "solr-cloud-architecture"}]
    assert render("material/cloud-architecture/index.html").status_code == 403


def test_directory_serves_index(tmp_path):
    setup_site(tmp_path, {"cloud-architecture": {"course": "c"}})
    frappe.session.user = "s@example.com"
    frappe._enrollments = [{"member": "s@example.com", "course": "c"}]
    assert render("material/cloud-architecture/").status_code == 200


def test_asset_content_type(tmp_path):
    setup_site(tmp_path, {"cloud-architecture": {"course": "c"}})
    frappe.session.user = "s@example.com"
    frappe._enrollments = [{"member": "s@example.com", "course": "c"}]
    res = render("material/cloud-architecture/app.js")
    assert res.status_code == 200
    assert "javascript" in res.mimetype


def test_path_traversal_is_refused(tmp_path):
    setup_site(tmp_path, {"cloud-architecture": {"course": "c"}})
    frappe.session.user = "s@example.com"
    frappe._enrollments = [{"member": "s@example.com", "course": "c"}]
    frappe._roles = ["System Manager"]          # even staff cannot escape the root
    res = render("material/cloud-architecture/../../secret.txt")
    assert res.status_code == 404


def test_lab_assets_share_the_same_gate(tmp_path):
    """Lab instructions live behind the same access rules as the slides."""
    setup_site(tmp_path, {"cloud-architecture": {"course": "c"}})
    frappe.session.user = "s@example.com"
    frappe._enrollments = [{"member": "s@example.com", "course": "c"}]
    assert render("material/cloud-architecture/lab.html").status_code == 200
    frappe._enrollments = []
    assert render("material/cloud-architecture/lab.html").status_code == 403


def test_extensionless_path_falls_back_to_html(tmp_path):
    """Frappe 301s /…/lab.html to /…/lab before any renderer runs, so the
    extension-less form must still find lab.html."""
    setup_site(tmp_path, {"cloud-architecture": {"courses": ["c"]}})
    frappe.session.user = "s@example.com"
    frappe._enrollments = [{"member": "s@example.com", "course": "c"}]
    res = render("material/cloud-architecture/lab")
    assert res.status_code == 200
    assert b"lab" in res.get_data()


def test_html_fallback_cannot_escape_the_root(tmp_path):
    setup_site(tmp_path, {"cloud-architecture": {"courses": ["c"]}})
    (tmp_path / "private" / "secret.html").write_text("nope")
    frappe.session.user = "s@example.com"
    frappe._roles = ["System Manager"]
    assert render("material/cloud-architecture/../../secret").status_code == 404


def test_shared_bundle_is_served_to_any_signed_in_user(tmp_path):
    """Decks reference /material/assets/deck.js. Gating that per chapter would
    serve an entitled student unstyled HTML with no reveal.js."""
    setup_site(tmp_path, {"cloud-architecture": {"courses": ["c"]}})
    shared = tmp_path / "private" / "material" / "assets"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "deck.js").write_text("reveal()")
    frappe.session.user = "s@example.com"
    frappe._enrollments = []                       # enrolled in nothing at all
    res = render("material/assets/deck.js")
    assert res.status_code == 200
    assert b"reveal()" in res.get_data()


def test_shared_bundle_still_requires_login(tmp_path):
    setup_site(tmp_path, {})
    shared = tmp_path / "private" / "material" / "assets"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "deck.js").write_text("reveal()")
    frappe.session.user = "Guest"
    assert render("material/assets/deck.js").status_code == 302


def test_missing_file_is_404(tmp_path):
    setup_site(tmp_path, {"cloud-architecture": {"course": "c"}})
    frappe.session.user = "s@example.com"
    frappe._roles = ["System Manager"]
    assert render("material/cloud-architecture/nope.html").status_code == 404


if __name__ == "__main__":
    import tempfile, traceback
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            with tempfile.TemporaryDirectory() as d:
                fn(Path(d)) if fn.__code__.co_argcount else fn()
            print(f"  ✓ {name}")
        except Exception:
            failed += 1
            print(f"  ✗ {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
