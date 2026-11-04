import json, tempfile, unittest\nfrom urllib.parse import parse_qs, urlsplit
from pathlib import Path
from unittest.mock import patch
import github_inventory as gi

class FakeResponse:
 def __init__(self,payload): self.payload=payload
 def __enter__(self): return self
 def __exit__(self,*args): return False
 def read(self): return json.dumps(self.payload).encode()

class GitHubInventoryTests(unittest.TestCase):
 def test_discovers_all_pages_until_short_page(self):
  calls=[]
  def fake(url,token,timeout=30):
   calls.append(url)
   page=int(parse_qs(urlsplit(url).query)["page"][0])
   if page==1:return [{"full_name":"owner/a","owner":{"login":"owner"},"default_branch":"main"}]
   return [{"full_name":"owner/b","owner":{"login":"owner"},"default_branch":"main"}] if page==2 else []
  with patch.object(gi,"_request_json",side_effect=fake):
   repos=gi.discover_repositories("owner","token",per_page=1)
  self.assertEqual([x["full_name"] for x in repos],["owner/a","owner/b"])
  self.assertEqual(len(calls),3)
 def test_invalid_owner_and_page_size_rejected(self):
  with self.assertRaises(ValueError):gi.discover_repositories("bad/owner","token")
  with self.assertRaises(ValueError):gi.discover_repositories("owner","token",per_page=101)
 def test_tree_reports_truncation_and_paths(self):
  with patch.object(gi,"_request_json",return_value={"truncated":True,"tree":[{"path":"README.md","type":"blob","size":20},{"path":"src","type":"tree"}]}):
   tree=gi.repository_tree("owner/repo","main","token")
  self.assertTrue(tree["truncated"])
  self.assertEqual(len(tree["entries"]),2)
 def test_atomic_snapshot_write(self):
  with tempfile.TemporaryDirectory() as tmp:
   target=Path(tmp)/"inventory.json"
   gi.save_inventory({"repository_count":2},target)
   self.assertEqual(json.loads(target.read_text())["repository_count"],2)
 def test_api_auth_errors_are_sanitized(self):
  import urllib.error
  with patch.object(gi.urllib.request,"urlopen",side_effect=urllib.error.HTTPError("u",403,"Forbidden",{},None)):
   with self.assertRaisesRegex(gi.GitHubInventoryError,"permission failed"):
    gi._request_json("https://api.github.com/user/repos","secret")
if __name__=="__main__":unittest.main()
