import hashlib,tempfile,unittest
from unittest.mock import Mock
from scotus_cloud.annotation_cards import CardTools

class LargeCardSourceTests(unittest.TestCase):
 def test_large_cached_document_returns_index_then_the_requested_page(self):
  url='https://court.example/petition.pdf';key=hashlib.sha256(url.encode()).hexdigest()
  with tempfile.TemporaryDirectory() as folder:
   tools=CardTools({'id':'fixture'},{},{},{},Mock(),Mock(),folder)
   tools.sources[key]={'url':url,'sha256':'document','pages':[{'page':n,'text':'Verifiable passage. '+'surrounding context '*500} for n in range(1,31)]}
   index=tools.source(url,'',0)
   self.assertEqual(index['source_id'],key);self.assertEqual(index['page_count'],30);self.assertEqual(index['pages'],[])
   selected=tools.source(url,'',23)
   self.assertEqual([p['page'] for p in selected['pages']],[23])
   tools.verify([{'source_id':key,'page':23,'quote':'Verifiable passage.'}])
   with self.assertRaises(ValueError):tools.verify([{'source_id':key,'page':23,'quote':'Invented passage.'}])
