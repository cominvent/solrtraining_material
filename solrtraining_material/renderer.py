"""Serve solrtraining.com course material from /material/… behind LMS access control.

Registered through the `page_renderer` hook, so Frappe asks this class first for
every website path. It answers only for /material/… and lets everything else fall
through to the normal LMS pages.

Access rules, in order:
  1. Not logged in            → redirect to /login (with a redirect-to back here)
  2. Staff role               → allowed (System Manager / Course Creator / Moderator)
  3. Enrolled in the course   → allowed  (LMS Enrollment)
  4. In a batch that includes the course → allowed  (LMS Batch Enrollment + Batch Course)
  5. otherwise                → 403

Material (slide decks, lab instructions, lab bundles) is plain static content
living OUTSIDE the web root, under
    sites/<site>/private/material/<chapter-slug>/…
so the only way to reach it is through this renderer. Content is deployed
separately (rsync from the solrtraining.com repo) — never baked into the image.
"""
from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path

import frappe
from werkzeug.wrappers import Response

MATERIAL_SUBPATH = ("private", "material")
MANIFEST = "material.json"          # {"<chapter-slug>": {"course": "<lms course name>"}}
STAFF_ROLES = {"System Manager", "Course Creator", "Moderator", "LMS Admin"}
INDEX = "index.html"


def material_root() -> Path:
    return Path(frappe.get_site_path(*MATERIAL_SUBPATH))


def load_manifest() -> dict:
    """chapter-slug → {course: …}. Deployed alongside the decks, so the app never
    hardcodes curriculum. Missing manifest entry ⇒ staff-only (fail closed)."""
    path = material_root() / MANIFEST
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        frappe.log_error(frappe.get_traceback(), "solrtraining_material: bad decks.json")
        return {}


def is_staff() -> bool:
    return bool(STAFF_ROLES & set(frappe.get_roles()))


def has_course_access(course: str) -> bool:
    """Enrolled directly, or a member of a batch that includes this course."""
    user = frappe.session.user
    if frappe.db.exists("LMS Enrollment", {"member": user, "course": course}):
        return True
    # Classroom cohorts: any batch the user is enrolled in that lists this course.
    batches = frappe.get_all("LMS Batch Enrollment", filters={"member": user},
                             pluck="batch")
    if batches and frappe.db.exists("Batch Course", {"parent": ["in", batches],
                                                     "course": course}):
        return True
    return False


def safe_material_file(rel_path: str) -> Path | None:
    """Resolve a request path inside the decks root, refusing traversal."""
    root = material_root().resolve()
    target = (root / rel_path).resolve()
    if root not in target.parents and target != root:
        return None
    if target.is_dir():
        target = target / INDEX
    return target if target.is_file() else None


class MaterialRenderer:
    """Frappe page renderer for /material/<chapter>/<file>."""

    def __init__(self, path: str, http_status_code: int | None = None):
        self.path = (path or "").strip("/")
        self.http_status_code = http_status_code or 200

    # ── routing ───────────────────────────────────────────────────────────
    def can_render(self) -> bool:
        return self.path == "material" or self.path.startswith("material/")

    # ── serving ───────────────────────────────────────────────────────────
    def render(self) -> Response:
        rel = self.path[len("material"):].lstrip("/")
        if not rel:
            return self._forbidden("No material requested.")

        chapter = rel.split("/")[0]

        if frappe.session.user == "Guest":
            target = frappe.utils.get_url(f"/material/{rel}")
            return Response(status=302, headers={
                "Location": f"/login?redirect-to={frappe.utils.quote(target)}"})

        if not is_staff():
            course = (load_manifest().get(chapter) or {}).get("course")
            if not course:
                return self._forbidden(
                    "This material is not published to students yet.")
            if not has_course_access(course):
                return self._forbidden(
                    "You do not have access to this course's material. "
                    "If you are attending a class, ask your instructor to add you.")

        f = safe_material_file(rel)
        if not f:
            return Response("Not found.", status=404, mimetype="text/plain")

        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        headers = {
            # Course material is proprietary: never let a shared cache keep a copy.
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        }
        # nginx does the file I/O when X-Accel is configured for the site;
        # otherwise we stream it ourselves (fine for deck-sized assets).
        accel = os.environ.get("SOLRTRAINING_MATERIAL_XACCEL")
        if accel:
            rel_to_root = f.relative_to(material_root().resolve())
            headers["X-Accel-Redirect"] = f"{accel.rstrip('/')}/{rel_to_root}"
            return Response(b"", status=200, mimetype=ctype, headers=headers)
        return Response(f.read_bytes(), status=200, mimetype=ctype, headers=headers)

    # ── helpers ───────────────────────────────────────────────────────────
    def _forbidden(self, message: str) -> Response:
        html = (f"<!doctype html><meta charset=utf-8>"
                f"<title>Course material — access</title>"
                f"<div style=\"font:17px/1.6 system-ui;max-width:38rem;margin:15vh auto;"
                f"padding:0 1.5rem;color:#14202c\">"
                f"<h1 style=\"color:#082b50;font-size:1.5rem\">Material not available</h1>"
                f"<p>{frappe.utils.escape_html(message)}</p>"
                f"<p><a href=\"/courses\" style=\"color:#1597d4\">← Back to your courses</a></p>"
                f"</div>")
        return Response(html, status=403, mimetype="text/html")
