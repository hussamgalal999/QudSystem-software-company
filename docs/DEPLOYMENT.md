# Deployment and rollback

## Current state

This branch is not a deployment. The final Hostinger website, serving directory and domain must be confirmed in the account before publishing. Do not overwrite an existing site without a backup and explicit destination approval. Do not change DNS or purchase/renew plans as part of code preparation.

## Release procedure

1. Inspect the Hostinger websites list and verify the intended website, plan and domain. Record the existing document root and redirects. If a site already exists, export a backup and confirm how it can be restored.
2. Use the confirmed HTTPS origin as `SITE_URL`. Run static tests, then build production. Do not upload a preview build: it intentionally contains `noindex,nofollow` and a crawl block.
3. Upload only the contents of `dist/` into the confirmed document root, preferably through a staging directory and atomic switch when supported. Never upload `.git`, `ops`, credentials, source files or development dependencies.
4. Configure a real HTTP 404 response using `404.html` as the error document. Test an unknown URL returns status 404, not a soft-404 status 200.
5. Confirm HTTPS certificate validity and the HTTP-to-HTTPS redirect. Do not enable HSTS `includeSubDomains` unless every subdomain is known to support HTTPS.
6. Configure security headers in the host: `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`, and frame restrictions. A Content Security Policy should restrict resources to this origin, disallow objects and framing, and explicitly allow the JSON-LD script by hash. Test it in report-only mode before enforcement. These headers are hosting-dependent and are not claimed as active by this branch.
7. Verify home, privacy, 404, robots, sitemap, llms.txt, favicon and social-card responses with the correct content types. Check canonical/schema URLs match the final host and there is no unintended `X-Robots-Tag: noindex` header.
8. Re-run browser checks against the deployed URL, inspect desktop/mobile screenshots and run mobile Lighthouse/PageSpeed. Measure field Core Web Vitals after sufficient real traffic exists. Local speed estimates are not field data.
9. Submit the verified sitemap through the owner's Search Console/Bing accounts if authorized. Request indexing only after the production content is ready. Track brand query visibility over time, without promising a position.

## Rollback

Retain the previous deployed files and server configuration before replacement. If the release fails checks, restore those files and configuration, verify HTTP status/HTTPS behavior and purge only the affected host cache if needed. A Git revert alone does not restore uploaded files or host settings.

## Parallel work

Open PR #42 (`seo-standard`) concerns the legacy v09 website. This branch leaves that tree untouched and puts the new site in `website/`. Do not serve both as duplicate indexable sites. Decide which entry point is authoritative; if migrating existing indexed pages, inventory them and add precise server-side permanent redirects to their closest valid replacement. Do not redirect unrelated pages blindly to the homepage.
