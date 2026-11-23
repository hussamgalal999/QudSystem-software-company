# QudSystem website

A responsive static website for QudSystem's software, AI and cybersecurity practice.

## Working tree

- `website/`: modern website source. This is the only publishable directory after building.
- `scripts/build_website.py`: dependency-free Python static build.
- `tests/`: static regression tests and Chromium/axe browser checks.
- `QudSystem.v09/`: original website kept unchanged for compatibility with the parallel `seo-standard` PR #42. It is not included in the new deployment output.
- `ops/revenue-operations/`, `ops/growth-engine/`, `ops/cvpen-growth/`: historical business material retained pending owner review. These are not website assets and are never published by this build.

The Qudron runtime, Cloudflare worker, related workflows and OpenDots submodule have been removed from this website branch. Their history remains in Git. The separate QUDRON repository is not changed. GitHub access used to maintain this repository is independent of its contents; no agent, token or account-control endpoint is needed on a static website.

## Build and verify

Python 3.10+ is required. No production JavaScript packages are needed.

```sh
python3 -m unittest discover -s tests -v
# Use the confirmed production HTTPS origin, not a placeholder:
SITE_URL=https://your-confirmed-domain.example python3 scripts/build_website.py
```

For a non-indexable local/staging preview:

```sh
python3 scripts/build_website.py --site-url https://preview.invalid --preview
python3 -m http.server 8080 --directory dist
```

Browser verification (Node 22+, development-only dependencies):

```sh
npm ci
npx playwright install chromium
npm run test:browser
```

The browser test starts its own temporary localhost server. Screenshots go to `/tmp` unless `SCREENSHOT_DIR` is set. Seven viewport widths, WCAG A/AA automated scans, keyboard menu behavior, local response errors and no-JavaScript navigation are checked. Automated tests do not replace manual visual review or prove complete accessibility conformance.

## Deploy safely

Read [deployment notes](docs/DEPLOYMENT.md) and the [20-point verification checklist](docs/WEBSITE_REVIEW.md).

Publish only the **contents of `dist/`**, never the repository root. Confirm the domain, existing website, backup and rollback before any replacement. This change does not deploy itself or activate billing. Canonical, sitemap, social-card and structured-data URLs are generated from the required `SITE_URL`.

Search rankings and inclusion in AI answers cannot be guaranteed. `llms.txt` is a reading aid, not a ranking instruction or an access-control mechanism.
