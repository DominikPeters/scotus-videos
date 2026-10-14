import copy,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.alignment import spoken_year,year_alignment_tokens,AlignmentReview
from scotus_cloud.court_metadata import normalized_case_source
from scotus_cloud.presentation_data import case_metadata

class MetadataYearTests(unittest.TestCase):
    def test_years_and_punctuation_generalize_beyond_2019(self):
        for text,expected in {'2019?':'twenty nineteen','2018,':'twenty eighteen','2026':'twenty twenty six',
            '1999.':'nineteen ninety nine','1900':'nineteen hundred','1905':'nineteen oh five','2000':'two thousand',
            '2009':'two thousand nine',' “2019?” ':'twenty nineteen'}.items():
            with self.subTest(text=text):self.assertEqual(spoken_year(text),expected)
        for text in ('$2019','2019.50','25-735','(Laughter.)','19','20999'):
            self.assertIsNone(spoken_year(text))

    def test_year_tokens_preserve_original_word_labels_in_sentences(self):
        labels=['<star>','In','<star>','2019?','<star>','yes.'];original=labels.copy()
        def preprocess(text,**kwargs):
            return [value for word in text.split() for value in ('*',' '.join(word))],[value for word in text.split() for value in ('<star>',word)]
        targets=year_alignment_tokens(['*','i n','*','','*','y e s'],labels,['In','2019?','yes.'],preprocess)
        self.assertEqual(targets[3],'t w e n t y n i n e t e e n');self.assertEqual(labels,original);self.assertEqual(len(targets),len(labels))
        with self.assertRaises(AlignmentReview):year_alignment_tokens([],[],['2019'],preprocess)

    def test_missing_and_null_court_metadata_use_existing_roster(self):
        job={'id':'fixture','case_name':'Example v. Case','docket':'25-735','argument_date':'2026-10-05'}
        transcript={'speakers':{}}
        for heard in (None,[None],[],{},[{}],[{'members':None}],[{'members':[None]}]):
            with self.subTest(heard=heard):
                source={'heard_by':heard,'timeline':None,'term':None};before=copy.deepcopy(source)
                result=case_metadata(job,transcript,{'case_metadata':source})
                self.assertEqual(len(result['heard_by'][0]['members']),9);self.assertEqual(result['term'],'2026')
                self.assertEqual(result['timeline'][0]['event'],'Argued');self.assertEqual(source,before)

    def test_valid_roster_is_preserved_without_changing_formatting_fields(self):
        member={'identifier':'justice','name':'Justice Name','last_name':'Name','thumbnail':{'href':'https://example.org/justice.jpg'}}
        source={'heard_by':[{'members':[member]}],'name':'A v. B','first_party':'A','question':'Existing question'}
        self.assertEqual(normalized_case_source(source),source)
        self.assertEqual(normalized_case_source({**source,'heard_by':[None,source['heard_by'][0]]})['heard_by'],source['heard_by'])

if __name__=='__main__':unittest.main()
