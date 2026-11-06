import json, os, unittest
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
  def fake(req,timeout=0,**kwargs):
   captured["url"]=req.full_url;captured["auth"]=req.get_header("X-mc-auth");return FakeResponse()
  with patch("metricool_client.open_credential_request",side_effect=fake):
   result=self.client().list_scheduled_posts("2026-11-01T00:00:00","2026-11-30T23:59:59")
  self.assertIn("start=2026-11-01",captured["url"])
  self.assertEqual(captured["auth"],"secret")
  self.assertIn("data",result)
 def test_published_posts_validate_network(self):
  with self.assertRaises(ValueError):self.client().list_published_posts("x","a","b")
 def test_create_post_is_draft_and_not_autopublished(self):
  captured={}
  mapping={"qudsystem":{"brand_id":"456","destination_id":"fb-page-1","network":"facebook"}}
  def fake(req,timeout=0,**kwargs):
   captured["body"]=json.loads(req.data);return FakeResponse()
  with patch.dict(os.environ, {"QUDRON_METRICOOL_APPROVED_BRAND_DESTINATIONS": json.dumps(mapping)}):
   with patch("metricool_client.open_credential_request",side_effect=fake):
    self.client().create_review_draft(
     "Draft copy","2026-11-20T10:00:00",
     content_brand="QudSystem",destination_id="fb-page-1",
    )
  self.assertTrue(captured["body"]["draft"])
  self.assertFalse(captured["body"]["autoPublish"])
  self.assertEqual(
   captured["body"]["providers"],
   [{"network":"facebook","id":"fb-page-1"}],
  )
 def test_metricool_draft_fails_closed_without_brand_destination_mapping(self):
  with patch("metricool_client.open_credential_request") as mocked:
   with self.assertRaises(mc.MetricoolError):
    self.client().create_review_draft(
     "Draft copy","2026-11-20T10:00:00",
     content_brand="QudSystem",destination_id="fb-page-1",
    )
   mocked.assert_not_called()
 def test_vision_guard_caption_cannot_be_misclassified_to_qudsystem(self):
  mapping={"qudsystem":{"brand_id":"456","destination_id":"fb-page-1","network":"facebook"}}
  with patch.dict(os.environ, {"QUDRON_METRICOOL_APPROVED_BRAND_DESTINATIONS": json.dumps(mapping)}):
   with patch("metricool_client.open_credential_request") as mocked:
    with self.assertRaisesRegex(mc.MetricoolError,"Vision Guard"):
     self.client().create_review_draft(
      "Vision Guard Systems — Your Security, Our Priority",
      "2026-11-20T10:00:00",content_brand="QudSystem",
      destination_id="fb-page-1",
     )
    mocked.assert_not_called()
 def test_metricool_draft_rejects_wrong_destination_even_for_approved_brand(self):
  mapping={"qudsystem":{"brand_id":"456","destination_id":"fb-page-1","network":"facebook"}}
  with patch.dict(os.environ, {"QUDRON_METRICOOL_APPROVED_BRAND_DESTINATIONS": json.dumps(mapping)}):
   with self.assertRaisesRegex(mc.MetricoolError,"does not match"):
    self.client().create_review_draft(
     "QudSystem product update","2026-11-20T10:00:00",
     content_brand="QudSystem",destination_id="wrong-page",
    )
 def test_vision_guard_requires_its_own_exact_approved_destination(self):
  mapping={"vision guard systems":{"brand_id":"vg-brand","destination_id":"vg-page","network":"facebook"}}
  mc.validate_brand_destination(
   text="Your Security, Our Priority — Vision Guard Systems",
   content_brand="Vision Guard Systems",brand_id="vg-brand",
   destination_id="vg-page",network="facebook",approved_brand_destinations=mapping,
  )
  with self.assertRaises(mc.MetricoolError):
   mc.validate_brand_destination(
    text="أمانك مسؤوليتنا — كاميرات مراقبة",
    content_brand="Vision Guard Systems",brand_id="7777628",
    destination_id="437731146095517",network="facebook",approved_brand_destinations=mapping,
   )


 def test_vision_guard_tagline_with_punctuation_cannot_be_misclassified(self):
  mapping={"qudsystem":{"brand_id":"456","destination_id":"fb-page-1","network":"facebook"}}
  with patch.dict(os.environ, {"QUDRON_METRICOOL_APPROVED_BRAND_DESTINATIONS": json.dumps(mapping)}):
   with self.assertRaisesRegex(mc.MetricoolError,"Vision Guard"):
    self.client().create_review_draft(
     "Your Security, Our Priority","2026-11-20T10:00:00",
     content_brand="QudSystem",destination_id="fb-page-1",
    )

 def test_metricool_destination_mapping_cannot_be_reused_for_another_network(self):
  mapping={"qudsystem":{"brand_id":"456","destination_id":"fb-page-1","network":"facebook"}}
  with patch.dict(os.environ, {"QUDRON_METRICOOL_APPROVED_BRAND_DESTINATIONS": json.dumps(mapping)}):
   with self.assertRaisesRegex(mc.MetricoolError,"brand/destination/network"):
    self.client().create_review_draft(
     "QudSystem product update","2026-11-20T10:00:00",
     network="youtube",content_brand="QudSystem",destination_id="fb-page-1",
    )

 def test_analytics_summary_aggregates_metrics(self):
  result=mc.summarize_posts([{"text":"a","metrics":{"reach":20,"likes":2}},{"content":"b","metrics":{"reach":30,"comments":3}}])
  self.assertEqual(result["totals"]["reach"],50)
  self.assertEqual(result["totals"]["likes"],2)
  self.assertEqual(result["totals"]["comments"],3)
 def test_credentials_are_required(self):
  with self.assertRaises(mc.MetricoolError):mc.MetricoolClient("","","")
if __name__=="__main__":unittest.main()
