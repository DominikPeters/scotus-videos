import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
from scotus_cloud.card_ocr import ocr_page

class OCRTests(unittest.TestCase):
 def test_selected_page_ocr_retains_pdf_identity_coordinates_and_cached_result(self):
  with tempfile.TemporaryDirectory() as folder:
   tools=Mock();tools.folder=Path(folder);pdf=Path(folder)/'source.pdf';pdf.write_bytes(b'%PDF-original')
   tools.sources={'source':{'url':'https://court.example/opinion.pdf','sha256':'original-pdf','pdf':pdf,'pages':[{'page':1,'width':600,'height':800,'text':'','words':[]}]}}
   def command(args,**kw):
    if args[0]=='pdftoppm':
     self.assertEqual(args[1:5],['-f','1','-l','1']);Image.new('RGB',(1200,1600),'white').save(args[-1]+'.png');return Mock()
    self.assertEqual(args[0],'tesseract');return Mock(stdout=b'left\ttop\twidth\theight\tconf\ttext\n20\t40\t100\t30\t95\tComplete\n130\t40\t80\t30\t95\tparagraph.\n')
   with patch('scotus_cloud.card_ocr.shutil.which',return_value='tesseract'),patch('scotus_cloud.card_ocr.subprocess.run',side_effect=command) as run:
    result=ocr_page(tools,'source',1);self.assertEqual(json.loads(result['contentItems'][0]['text'])['text'],'Complete paragraph.')
    self.assertEqual(tools.sources['source']['sha256'],'original-pdf');self.assertEqual(tools.sources['source']['pages'][0]['words'][0]['box'],[10,20,60,35])
    self.assertTrue(ocr_page(tools,'source',1)['cached']);self.assertEqual(run.call_count,2)
