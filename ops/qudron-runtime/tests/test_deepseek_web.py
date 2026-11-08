import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import deepseek_web as dw
class Resp:
 def __init__(self,payload):self.payload=payload
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def read(self):return json.dumps(self.payload).encode()
class WebTests(unittest.TestCase):
 def test_search_requires_key_and_explicit_daily_cap(self):
  with patch.dict(os.environ,{"DEEPSEEK_API_KEY":"","QUDRON_WEB_SEARCH_MAX_DAILY_CALLS":"5"},clear=True),self.assertRaisesRegex(dw.WebResearchError,"DEEPSEEK_API_KEY"):dw.search_web("official model release")
 def test_search_is_metered_and_returns_structured_sources(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp,patch.dict(os.environ,{"DEEPSEEK_API_KEY":"test","QUDRON_WEB_SEARCH_MAX_DAILY_CALLS":"2","QUDRON_WEB_SEARCH_DB":str(Path(tmp)/"usage.sqlite3")},clear=True),patch("deepseek_web.open_credential_request",return_value=Resp({"results":[{"title":"Source","url":"https://example.com","summary":"Verified"}]})):
   result=dw.search_web("official model release",count=3)
   self.assertEqual(result["usage"]["daily_calls"],1)
   self.assertEqual(result["cost_usd"],dw.COST_PER_SUCCESS_USD)
 def test_daily_call_cap_fails_closed(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp,patch.dict(os.environ,{"DEEPSEEK_API_KEY":"test","QUDRON_WEB_SEARCH_MAX_DAILY_CALLS":"1","QUDRON_WEB_SEARCH_DB":str(Path(tmp)/"usage.sqlite3")},clear=True),patch("deepseek_web.open_credential_request",return_value=Resp({"results":[{"url":"https://example.com"}]})):
   dw.search_web("query one")
   with self.assertRaisesRegex(dw.WebResearchError,"Daily"):dw.search_web("query two")
 def test_fetch_rejects_local_and_non_https_targets(self):
  for url in ("http://example.com","https://localhost/path","https://127.0.0.1/path","https://user:pass@example.com"):
   with self.assertRaises(ValueError):dw._safe_url(url)
 def test_query_and_count_are_bounded(self):
  with self.assertRaises(ValueError):dw.search_web("")
  with self.assertRaises(ValueError):dw.search_web("valid query",count=11)
if __name__=="__main__":unittest.main()
