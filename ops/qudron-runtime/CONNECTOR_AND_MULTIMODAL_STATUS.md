# Qudron connector and multimodal execution wave

## Implemented in this branch

### GitHub inventory
- github_inventory.py performs authenticated, paginated GitHub repository discovery across owner, collaborator and organization affiliations.
- Optional recursive Git Trees metadata scan indexes paths and file sizes without cloning or executing repositories.
- Atomic JSON snapshot persistence; truncated trees and bounded scans are reported explicitly.
- github_repository_catalog.snapshot.json records a connected-account discovery snapshot of 503 repositories at 2026-11-04, including 41 marked private in connector search results. This is a point-in-time catalog, not proof that every file in all repositories has been read.
- Runtime sync requires GITHUB_OWNER and a fine-grained GITHUB_TOKEN with read-only Metadata access to every intended repo. Private access depends on token resource selection and permissions.

### Metricool
- metricool_client.py uses the official Metricool API with X-Mc-Auth, userId and blogId.
- Read operations: scheduled posts and published Facebook/Instagram post analytics.
- Write operation: create_review_draft only; it sets draft=true and autoPublish=false. No publish, delete or update action is exposed.
- Analytics summarizer calculates aggregate post metrics when returned by Metricool.
- API access requires Metricool Advanced or Custom plan and a token from Account Settings > API. The ChatGPT Metricool connection is separate from Qudron's server credential and does not automatically populate its environment.

### Vision and image-to-code groundwork
- vision_adapter.py reads only files under QUDRON_IMAGE_ROOT, accepts JPEG/PNG/WebP/GIF, enforces a bounded image size and sends a multimodal OpenAI-compatible request.
- It reuses Qudron's existing model spend reservation and global concurrency controls.
- The configured endpoint must actually support vision; text-only endpoints will not satisfy the request.
- This adapter is a tested callable module; it is not yet a public upload endpoint, automatic GitHub issue attachment processor or complete design-to-code pipeline.

## Connected Metricool account observations
The connected Metricool brand is hussamgalal99, blog ID 7777628, timezone Africa/Cairo, with Facebook, Instagram and YouTube connection metadata. A recent analytics pull returned four Facebook posts from 31 Oct–2 Nov 2026; visible impressions were 3, 5, 8 and 6, and reach was 2, 3, 2 and 1. This small early sample is not enough to claim reliable trends.
The scheduled-post calendar contained pending Facebook posts through 20 Nov 2026. They remain in Metricool; this adapter does not rewrite or publish them.

## AI model candidates found on 2026-11-04
- DeepSeek V4.1 Flash: official API candidate with native multimodal visual understanding; API model ID deepseek-flash.
- Xiaomi MiMo V2.6 Pro, Flash and Pro UltraSpeed: current multimodal flagship, economical and high-speed variants.
- Meta Muse Wonder and Muse Spark Open: advanced agentic/multimodal options. Muse Spark Open is 816B total / 42B active with a 1M-token context window; this is not realistic to run on a 10 GB desktop.
These are candidates for a measured provider bake-off, not currently connected or enabled by this code.

## Still not live
- No GitHub token is installed into the Qudron host; no dynamic repository scan has run from Qudron itself.
- No Metricool API token is installed into Qudron; the connected ChatGPT app can read the account, but Qudron cannot inherit that session.
- No Qudron host or Cloudflare Worker is deployed; the code is not running 24/7 yet.
- No SMS, international voice calling or offline-device notification gateway is connected.
- No consumer ChatGPT anonymous-web access or account/session bypass is implemented.
- No image upload endpoint or full image-to-React/Next/Figma pipeline is released; the bounded local-image vision callable is the first tested adapter.
