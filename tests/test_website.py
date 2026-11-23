import importlib.util
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('builder', ROOT / 'scripts/build_website.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.tags=[]; self.feed(text)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag,dict(attrs)))

class WebsiteTests(unittest.TestCase):
    def setUp(self):
        builder.build('https://example.test')
        self.dist=ROOT/'dist'
        self.home=(self.dist/'index.html').read_text()
        self.page=Page(self.home)
    def test_sitemap(self):
        tree=ET.parse(self.dist/'sitemap.xml')
        locs=[n.text for n in tree.findall('.//{*}loc')]
        self.assertEqual(locs,['https://example.test/','https://example.test/privacy.html'])
    def test_robots_allows_assets(self):
        text=(self.dist/'robots.txt').read_text()
        self.assertIn('Allow: /',text);self.assertNotIn('Disallow:',text)
    def test_production_is_indexable(self):
        for name in ['index.html','privacy.html']:
            self.assertNotIn('noindex',(self.dist/name).read_text())
        self.assertIn('noindex',(self.dist/'404.html').read_text())
    def test_canonicals(self):
        for name,suffix in [('index.html','/'),('privacy.html','/privacy.html')]:
            tags=Page((self.dist/name).read_text()).tags
            self.assertEqual([a['href'] for t,a in tags if t=='link' and a.get('rel')=='canonical'],['https://example.test'+suffix])
    def test_title_description(self):
        for name in ['index.html','privacy.html']:
            text=(self.dist/name).read_text();tags=Page(text).tags
            self.assertIn('<title>',text)
            descriptions=[a['content'] for t,a in tags if t=='meta' and a.get('name')=='description']
            self.assertEqual(len(descriptions),1);self.assertTrue(80<=len(descriptions[0])<=200)
    def test_one_h1(self):
        self.assertEqual(sum(t=='h1' for t,a in self.page.tags),1)
    def test_heading_hierarchy(self):
        previous=0
        for tag,a in self.page.tags:
            if tag in ['h1','h2','h3','h4','h5','h6']:
                level=int(tag[1]);self.assertLessEqual(level,previous+1);previous=level
    def test_alt_and_dimensions(self):
        for tag,attrs in self.page.tags:
            if tag=='img':
                for key in ['alt','width','height']:self.assertIn(key,attrs)
    def test_schema(self):
        import re
        schema=json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',self.home,re.S)[1])
        self.assertEqual([x['@type'] for x in schema['@graph']],['Organization','WebSite'])
        self.assertEqual(schema['@graph'][0]['url'],'https://example.test/')
    def test_local_links(self):
        for name in ['index.html','privacy.html']:
            page=Page((self.dist/name).read_text());ids={a['id'] for t,a in page.tags if 'id'in a}
            for tag,attrs in page.tags:
                for attr in ['href','src']:
                    link=attrs.get(attr,'')
                    if not link or link.startswith('https://'):continue
                    if link.startswith('#'):self.assertIn(link[1:],ids);continue
                    self.assertTrue((self.dist/link.split('#')[0]).is_file(),link)
    def test_clean_paths(self):
        self.assertTrue((self.dist/'privacy.html').is_file())
        self.assertFalse(any(' ' in str(p.relative_to(self.dist)) for p in self.dist.rglob('*')))
    def test_payload_budget(self):
        self.assertLess(sum(p.stat().st_size for p in self.dist.rglob('*') if p.is_file()),120000)
        self.assertLess((self.dist/'assets/site.js').stat().st_size,2000)
    def test_mobile_and_zoom(self):
        self.assertIn('width=device-width',self.home);self.assertNotIn('maximum-scale',self.home)
        self.assertIn('prefers-reduced-motion',(self.dist/'assets/site.css').read_text())
    def test_no_insecure_resources(self):
        self.assertNotIn('http://',self.home)
    def test_social_image(self):
        import struct
        data=(self.dist/'assets/social-card.png').read_bytes()
        self.assertEqual(struct.unpack('>II',data[16:24]),(1200,630))
        self.assertIn('https://example.test/assets/social-card.png',self.home)
    def test_llms(self):
        self.assertIn('QUD System',(self.dist/'llms.txt').read_text())
        self.assertNotIn('{{SITE_URL}}',(self.dist/'llms.txt').read_text())
    def test_preview_noindex(self):
        builder.build('https://preview.invalid',preview=True)
        self.assertIn('noindex,nofollow',(self.dist/'index.html').read_text())
        self.assertIn('Disallow: /',(self.dist/'robots.txt').read_text())
    def test_origin_validation(self):
        for url in ['http://example.test','https://example.test/path','https://example.test/?x=1','https://u:p@example.test','https://example.test/#x','https://example.test/\"']:
            with self.subTest(url=url),self.assertRaises(ValueError):builder.build(url)
    def test_publish_allowlist(self):
        self.assertEqual({p.name for p in self.dist.iterdir()},{'index.html','privacy.html','404.html','assets','llms.txt','sitemap.xml','robots.txt','build-info.json'})
        self.assertFalse(any('qudron' in str(p).lower() for p in self.dist.rglob('*')))
    def test_no_unreplaced_tokens(self):
        for p in self.dist.rglob('*'):
            if p.suffix in ['.html','.xml','.txt']:self.assertNotIn('{{',p.read_text())

if __name__=='__main__':unittest.main()
