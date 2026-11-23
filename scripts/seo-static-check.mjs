#!/usr/bin/env node
/**
 * Static-site 20-point SEO gate (no server needed).
 * Usage: node scripts/seo-static-check.mjs --dir . --exclude shared-header.html,hero-sections.html,header.html
 */
import { readFileSync, readdirSync, statSync, existsSync } from "fs"
import { join, relative } from "path"

const arg = (n) => { const i = process.argv.indexOf(n); return i >= 0 ? process.argv[i + 1] : null }
const DIR = arg("--dir") || "."
const EXCLUDE = (arg("--exclude") || "").split(",").filter(Boolean)

const failures = []
const fail = (f, m) => failures.push(`${f}: ${m}`)

const htmlFiles = []
;(function walk(d) {
  for (const e of readdirSync(d)) {
    const p = join(d, e)
    if (statSync(p).isDirectory()) { if (!/node_modules|\.git|assets|css|js$/.test(e)) walk(p) }
    else if (e.endsWith(".html")) htmlFiles.push(p)
  }
})(DIR)

for (const p of htmlFiles) {
  const rel = relative(DIR, p)
  if (EXCLUDE.some((x) => rel.includes(x))) continue
  const s = readFileSync(p, "utf8")
  if (!/<title>[^<]+<\/title>/.test(s)) fail(rel, "missing <title>")
  if (!/<meta name="description" content="[^"]{20,}"/.test(s)) fail(rel, "missing/short meta description")
  if (!/<link rel="canonical" href="https?:\/\//.test(s)) fail(rel, "missing canonical")
  if (!/property="og:image"/.test(s)) fail(rel, "missing og:image")
  if (!/name="viewport"/.test(s)) fail(rel, "missing viewport (mobile)")
  const h1 = (s.match(/<h1[\s>]/g) || []).length
  if (h1 !== 1) fail(rel, `expected exactly 1 <h1>, found ${h1}`)
  for (const m of s.matchAll(/<img[^>]*>/g)) if (!/alt="/.test(m[0])) fail(rel, `img without alt: ${m[0].slice(0, 60)}`)
}

for (const f of ["sitemap.xml", "robots.txt", "llms.txt", "og-image.png"])
  if (!existsSync(join(DIR, f))) fail(f, "missing required SEO file")
if (existsSync(join(DIR, "robots.txt")) && !/sitemap:/i.test(readFileSync(join(DIR, "robots.txt"), "utf8")))
  fail("robots.txt", "missing Sitemap: line")

if (failures.length) {
  console.error(`Static SEO gate FAILED — ${failures.length} problem(s):`)
  for (const f of [...new Set(failures)]) console.error("  x " + f)
  process.exit(1)
}
console.log(`Static SEO gate PASSED — ${htmlFiles.length} pages checked in ${DIR}.`)
