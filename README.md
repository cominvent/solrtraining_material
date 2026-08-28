# solrtraining_material

A small [Frappe](https://frappeframework.com) app that serves static course
material (slide decks, lab instructions, lab bundles) at `/material/…` on a [Frappe LMS](https://github.com/frappe/lms) site, behind the
site's own login and course access.

It contains **no course content** — only the doorman. The material itself is
deployed separately as files.

## How it works

The app registers a `page_renderer`, so Frappe asks it first for every website
path. It answers only for `/material/…`:

| Visitor | Result |
|---|---|
| Not logged in | 302 to `/login?redirect-to=…` |
| Staff (System Manager · Course Creator · Moderator · LMS Admin) | served |
| Enrolled in the course that owns the chapter (`LMS Enrollment`) | served |
| Member of a batch that includes that course (`LMS Batch Enrollment` + `Batch Course`) | served |
| Anyone else | 403 with a friendly page |

Access is **fail-closed**: a chapter missing from the manifest is staff-only, and
path traversal out of the material root is refused.

### Where the files live

```
sites/<site>/private/material/material.json       ← manifest: chapter slug → course
sites/<site>/private/material/<chapter-slug>/…    ← deck (index.html, assets),
                                                     lab.html, lab-<slug>.zip
```

`private/` is outside the web root, so nginx cannot serve these directly — every
request goes through the access check.

`material.json`:

```json
{
  "cloud-architecture": { "course": "solr-cloud-architecture" }
}
```

### Serving large assets

Set `SOLRTRAINING_MATERIAL_XACCEL` (e.g. `/protected-material`) and add a matching
`internal` nginx location pointing at the material directory; the app then returns
an `X-Accel-Redirect` and nginx streams the file. Without it, the app streams
the bytes itself — fine for decks and lab bundles.

## Install

```sh
bench get-app https://github.com/cominvent/solrtraining_material
bench --site <site> install-app solrtraining_material
```

In a `frappe_docker` image build, add it to `apps.json`.

## Granting a class access to a chapter's material

Add the course to the students' `LMS Batch` in the LMS UI (Batch → Courses) —
everyone in that batch can open that chapter's material immediately, no per-student work.

## Tests

```sh
python3 tests/test_renderer.py     # or: pytest -q
```

The tests stub the `frappe` module, so the access rules can be verified on a
laptop and in CI without a Frappe installation.

---
© Cominvent AS · licensed under the Apache License 2.0. Apache Solr is a trademark of the Apache Software
Foundation; solrtraining.com is an independent training provider.
