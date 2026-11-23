# Website review and coordination checklist

This applies to the new `website/` build, not the untouched legacy v09 template. Local checks are not claims about the live host. No ranking guarantees are made.

## Requested 20-point checklist

| # | Item | Verified state | Evidence / remaining work |
|---|---|---|---|
| 1 | sitemap.xml | Pass locally; live pending | Generated XML lists home and privacy under the required SITE_URL. |
| 2 | robots.txt | Pass locally; live pending | Production permits assets/crawling; preview blocks crawling. Verify host headers. |
| 3 | noindex | Pass locally | Production content indexable, preview noindex/nofollow, 404 noindex. |
| 4 | canonical | Pass locally; final origin pending | One absolute self-canonical per content page, generated from SITE_URL. |
| 5 | title | Pass locally | Descriptive brand-specific page titles. |
| 6 | meta description | Pass locally | One description per content page, checked length range 80-200 characters. |
| 7 | one H1 | Pass locally | Exactly one H1 on homepage; privacy/404 each have their own. |
| 8 | heading hierarchy | Pass locally | Homepage H1/H2/H3 ordering checked without skipped levels. |
| 9 | image alt | Pass locally | Decorative brand icon has empty alt; informative system graphic has an accessible label. |
| 10 | schema | Pass locally; discovery pending | Parseable Organization and WebSite JSON-LD, no fabricated reviews, customers or certifications. |
| 11 | internal links | Pass locally | Sections, privacy and reading-aid links are present. All homepage fragments resolve. |
| 12 | broken links | Pass for local build | Local targets/assets checked; zero failed browser responses. External GitHub repo verified separately. Live host redirects/statuses pending. |
| 13 | clean slugs | Pass locally | Root, privacy.html, descriptive assets; no query-based navigation or spaces. |
| 14 | optimized images | Pass locally | SVG brand icon; CSS hero illustration; 1200x630 social PNG is 30,579 bytes. No third-party font downloads. |
| 15 | Core Web Vitals | Pending live field data | Preview output is 56,405 bytes across 11 files, including social card. This is not LCP/INP/CLS field evidence. |
| 16 | mobile | Pass local automated and visual checks | Widths 320, 375, 390, 768, 1024, 1440, 1920; no horizontal overflow. |
| 17 | HTTPS | Pending live hosting | Build rejects non-HTTPS origin. Certificate/redirect behavior must be tested after deployment. |
| 18 | og:image | Pass locally; live pending | Absolute social image URL generated; image dimensions checked. |
| 19 | console errors | Pass local Chromium | Zero page/console errors across seven widths. Live hosting check still needed. |
| 20 | llms.txt | Pass locally; adoption not guaranteed | Brand aliases, canonical sources and factual limits. This does not guarantee AI inclusion or ranking. |

## Beyond the checklist

- WCAG-tagged axe checks: zero automated violations across seven homepage widths plus privacy. This is not a complete accessibility certification.
- Visible focus, keyboard skip link, native details/summary, labelled navigation, Escape-to-close mobile menu and 44px menu target.
- Functional navigation without JavaScript, reduced-motion and forced-colors support; zoom is not disabled.
- No analytics, cookies, contact forms, external scripts, external fonts or production package dependencies. Privacy page explains ordinary hosting logs and external links.
- Explicit static publish allowlist: only website files copied into dist. No GitHub tokens, server-side account-control endpoints or agent executors in the deployable site.
- Preview indexing guard, final-origin validation, payload budget, schema parse checks and reproducible locked browser-test dependencies.
- Deployment notes cover backup/rollback, real 404 status, HTTPS redirects, host security headers, sitemap submission, duplicate-content avoidance and migration redirects. These remain host-level work until verified.
- Content is intentionally cautious: project maturity varies; no invented customer count, awards, uptime or commercial availability.
- Translation/hreflang is not claimed: this first site is English only. Add a reviewed Arabic edition if requested, rather than publishing an unreviewed automatic translation.

## Parallel-agent coordination

Existing PR #42 (`seo-standard`) at https://github.com/hussamgalal999/QudSystem-software-company/pull/42 edits the v09 website. This branch does not modify v09 or that branch. New source, build, tests and documentation are isolated. Before merging/deploying, choose the authoritative serving root and reconcile any final destination changes. Do not serve old and new sites as duplicate indexable copies.

## Cleanup decision

Removed **78 tracked paths** on this branch: Qudron runtime (63), Cloudflare agent (10), their three workflows, `.gitmodules`, and the OpenDots submodule gitlink. Git history remains recoverable. Nothing in the separate QUDRON repository changed. Keeping credential-bearing agent access in a static marketing site adds risk and is unnecessary; maintenance GitHub access is independent.

Retained: original v09 website, branding assets, license, existing documentation automation, and **15 business/growth Markdown documents** under `ops/revenue-operations`, `ops/growth-engine`, `ops/cvpen-growth`. The latter mix non-Qudron business records and historical agent references, so they are retained for owner review, never included in dist. This is a website-only deployment artifact, not a claim that every historical business document has been removed from the repository.

## Validation record

- 20/20 Python regression tests passed.
- Seven Chromium viewport scenarios passed, with zero automated axe violations, overflow, console/page errors or failed local responses.
- No-JavaScript navigation and privacy-page axe scan passed.
- Desktop/mobile screenshots inspected directly.
- `npm ci` and dependency audit: 5 packages audited, zero reported vulnerabilities at execution time.
- `git diff --check` passed.
- Hosted CI status and live deployment have not been verified. Billing may prevent hosted workflows from running; local results do not stand in for a hosted run.
