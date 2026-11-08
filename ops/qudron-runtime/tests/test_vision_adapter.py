import os,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
import vision_adapter as va
class VisionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/"images";self.root.mkdir()
  self.img=self.root/"screen.png";self.img.write_bytes(b"fake-png")
  self.env={"QUDRON_IMAGE_ROOT":str(self.root),"LLM_BALANCED_BASE_URL":"https://vision.example/v1","LLM_BALANCED_MODEL":"vision-test","LLM_BALANCED_API_KEY":"test"}
 def tearDown(self):self.tmp.cleanup()
 def test_rejects_path_outside_root(self):
  outside=Path(self.tmp.name)/"outside.png";outside.write_bytes(b"x")
  with patch.dict(os.environ,self.env,clear=True),self.assertRaisesRegex(va.VisionError,"outside"):va._safe_image(outside)
 def test_rejects_unsupported_file_type(self):
  bad=self.root/"file.txt";bad.write_text("x")
  with patch.dict(os.environ,self.env,clear=True),self.assertRaisesRegex(va.VisionError,"Only JPEG"):va._safe_image(bad)
 def test_uses_budget_slot_and_multimodal_payload(self):
  captured={}
  class Response:
   def __enter__(self):return self
   def __exit__(self,*a):return False
   def read(self):return b'{"choices":[{"message":{"content":"Visible text"}}],"usage":{"prompt_tokens":20,"completion_tokens":10,"total_tokens":30}}'
  def fake(req,timeout=0,**kwargs):
   captured["body"]=json.loads(req.data.decode());captured["auth"]=req.get_header("Authorization");return Response()
  with patch.dict(os.environ,self.env,clear=True),patch.object(va.worker,"reserve_model_budget",return_value="reserve") as reserve,patch.object(va.worker,"acquire_model_call_slot",return_value="slot"),patch.object(va.worker,"record_model_usage") as record,patch.object(va.worker,"release_model_call_slot") as release,patch.object(va.worker,"release_model_budget_reservation") as release_budget,patch("vision_adapter.open_credential_request",side_effect=fake):
   result=va.analyze_image(self.img,"Extract visible code")
  self.assertEqual(result,"Visible text");self.assertEqual(captured["auth"],"Bearer test")
  self.assertTrue(captured["body"]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
  reserve.assert_called_once();record.assert_called_once();release.assert_called_once_with("slot");release_budget.assert_called_once_with(None)
 def test_fails_closed_when_budget_is_missing(self):
  with patch.dict(os.environ,self.env,clear=True),patch.object(va.worker,"reserve_model_budget",side_effect=RuntimeError("budget missing")),self.assertRaisesRegex(RuntimeError,"budget missing"):va.analyze_image(self.img,"Describe image")
if __name__=="__main__":unittest.main()
