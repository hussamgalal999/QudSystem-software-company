#!/usr/bin/env python3
"""Build only the static website. No runtime or repository files are published."""
import argparse
import json
import os
from pathlib import Path
import shutil
from urllib.parse import urlparse
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]

def build(site_url, preview=False):
    parsed = urlparse(site_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('SITE_URL must be a bare HTTPS origin, without credentials, path, query or fragment')
    if any(c in site_url for c in '<>\"\'\\\n\r\t'):
        raise ValueError('Invalid character in SITE_URL')
    origin = site_url.rstrip('/')
    source, target = ROOT / 'website', ROOT / 'dist'
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    for path in target.rglob('*'):
        if path.is_file() and path.suffix in ('.html', '.txt', '.xml'):
            text = path.read_text().replace('{{SITE_URL}}', origin)
            if preview and path.suffix == '.html':
                text = text.replace('content="index,follow,max-image-preview:large"', 'content="noindex,nofollow"')
            path.write_text(text)
    routes = ['/', '/privacy.html']
    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    sitemap += ''.join(f'  <url><loc>{escape(origin + route)}</loc></url>\n' for route in routes)
    (target / 'sitemap.xml').write_text(sitemap + '</urlset>\n')
    robots = 'User-agent: *\n' + ('Disallow: /\n' if preview else 'Allow: /\n') + f'\nSitemap: {origin}/sitemap.xml\n'
    (target / 'robots.txt').write_text(robots)
    (target / 'build-info.json').write_text(json.dumps({'site_url': origin, 'preview': preview}, indent=2) + '\n')
    print(f'Built {sum(p.is_file() for p in target.rglob("*"))} files in dist/ ({"preview: noindex" if preview else "production"})')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--site-url', default=os.environ.get('SITE_URL'))
    parser.add_argument('--preview', action='store_true')
    args = parser.parse_args()
    if not args.site_url:
        parser.error('Set SITE_URL or pass --site-url. The final production domain must be confirmed first.')
    try:
        build(args.site_url, args.preview)
    except ValueError as exc:
        parser.error(str(exc))
