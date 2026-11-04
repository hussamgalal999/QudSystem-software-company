import json, unittest
from unittest.mock import patch
import metricool_client as mc

class FakeHeaders(dict):
 def get(self,k,d=None):return super().get(k,d)
class FakeResponse:
 headers=FakeHeaders({"Content-Type":"application/json"})
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def read(self):return b'{"data":[{"text":"ok"}]}'

class MetricoolTests(unittest.TestCase):
 def client(self):return mc.MetricoolClient("secret","123","456")
 def test_scheduled_posts_use_official_range_params(self):
  captured={}
  def fake(req,timeout):
   captured["url"]=req.full_url;captured["auth"]=req.get_header("X-mc-auth");return FakeResponse()
  with patch("metricool_client.urllib.request.urlopen",side_effect=fake):
   result=self.client().list_scheduled_posts("2026-11-01T00:00:00","2026-11-30T23:59:59")
  self.assertIn("start=2026-11-01",captured["url"])
  self.assertEqual(captured["auth"],"secret")
  self.assertIn("data",result)
 def test_published_posts_validate_network(self):
  with self.assertRaises(ValueError):self.client().list_published_posts("x","a","b")
 def test_create_post_is_draft_and_not_autopublished(self):
  captured={}
  def fake(req,timeout):
   captured["body"]=json.loads(req.data);return FakeResponse()
  with patch("metricool_client.urllib.request.urlopen",side_effect=fake):
   self.client().create_review_draft("Draft copy","2026-11-20T10:00:00")
  self.assertTrue(captured["body"]["draft"])
  self.assertFalse(captured["body"]["autoPublish"])
 def test_analytics_summary_aggregates_metrics(self):
  result=mc.summarize_posts([{"text":"a","metrics":{"reach":20,"likes":2}},{"content":"b","metrics":{"reach":30,"comments":3}}])
  self.assertEqual(result["totals"]["reach"],50)
  self.assertEqual(result["totals"]["likes"],2)
  self.assertEqual(result["totals"]["comments"],3)
 def test_credentials_are_required(self):
  with self.assertRaises(mc.MetricoolError):mc.MetricoolClient("","","")
if __name__=="__main__":unittest.main()
