# solrtraining_decks

A small [Frappe](https://frappeframework.com) app that serves static slide decks
at `/decks/…` on a [Frappe LMS](https://github.com/frappe/lms) site, behind the
site's own login and course access.

It contains **no course content** — only the doorman. Decks are deployed
separately as files.

## How it works

The app registers a `page_renderer`, so Frappe asks it first for every website
path. It answers only for `/decks/…`:

| Visitor | Result |
|---|---|
| Not logged in | 302 to `/login?redirect-to=…` |
| Staff (System Manager · Course Creator · Moderator · LMS Admin) | served |
| Enrolled in the course that owns the deck (`LMS Enrollment`) | served |
| Member of a batch that includes that course (`LMS Batch Enrollment` + `Batch Course`) | served |
| Anyone else | 403 with a friendly page |

Access is **fail-closed**: a deck missing from the manifest is staff-only, and
path traversal out of the deck root is refused.

### Where the files live

```
sites/<site>/private/decks/decks.json          ← manifest: slug → course
sites/<site>/private/decks/<chapter-slug>/…    ← the built deck (index.html, assets)
```

`private/` is outside the web root, so nginx cannot serve these directly — every
request goes through the access check.

`decks.json`:

```json
{
  "cloud-architecture": { "course": "solr-cloud-architecture" }
}
```

### Serving large assets

Set `SOLRTRAINING_DECKS_XACCEL` (e.g. `/protected-decks`) and add a matching
`internal` nginx location pointing at the decks directory; the app then returns
an `X-Accel-Redirect` and nginx streams the file. Without it, the app streams
the bytes itself — fine for slide decks.

## Install

```sh
bench get-app https://github.com/cominvent/solrtraining_decks
bench --site <site> install-app solrtraining_decks
```

In a `frappe_docker` image build, add it to `apps.json`.

## Granting a class access to a deck

Add the course to the students' `LMS Batch` in the LMS UI (Batch → Courses) —
everyone in that batch can open the deck immediately, no per-student work.

## Tests

```sh
python3 tests/test_renderer.py     # or: pytest -q
```

The tests stub the `frappe` module, so the access rules can be verified on a
laptop and in CI without a Frappe installation.

---
© Cominvent AS · MIT licensed. Apache Solr is a trademark of the Apache Software
Foundation; solrtraining.com is an independent training provider.
