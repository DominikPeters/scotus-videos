import unittest
from pipeline import parse_docket, quote_word_indices, validate_mentions, printed_page_label


class EvidenceTests(unittest.TestCase):
    def test_appendix_pagination_ignores_ecf_document_numbers(self):
        words = [{'text':'27','box':[297,8,315,18]},
                 {'text':'29a','box':[50,35,73,46]},
                 {'text':'6','box':[302,750,310,761]}]
        self.assertEqual(printed_page_label(words,612,792),'29a')
        self.assertEqual(printed_page_label(words[:1]+words[2:],612,792),'6')
        self.assertIsNone(printed_page_label(words[:1],612,792))

    def test_docket_excludes_service_and_preserves_distinct_appendix(self):
        html = '''<table id="proceedings"><tr><td>Sep 18 2025</td><td>Application filed.
        <a href="/brief.pdf">Main Document</a><a href="/appendix.pdf">Lower Court Orders/Opinions</a>
        <a href="/service.pdf">Proof of Service</a></td></tr></table>'''
        docs = parse_docket(html, "https://www.supremecourt.gov/docket/case.html")
        self.assertEqual([d['url'] for d in docs], ["https://www.supremecourt.gov/brief.pdf", "https://www.supremecourt.gov/appendix.pdf"])
        self.assertEqual(docs[0]['title'], "Application filed.")
        self.assertNotEqual(docs[0]['id'], docs[1]['id'])

    def test_quote_matches_pdf_line_breaks_and_hyphenation(self):
        page = {'words':[{'text':word} for word in 'unless sooner re- moved for cause by the President'.split()]}
        self.assertEqual(quote_word_indices(page,'unless sooner removed for cause by the President'),list(range(9)))
        with self.assertRaises(ValueError):
            quote_word_indices(page,'unless sooner removed by Congress for financial negligence')

    def test_timestamps_are_derived_and_fabricated_evidence_rejected(self):
        rows=[{'id':'s0t0b0','start':12.5,'stop':20,'text':'The President may remove a governor for cause.'}]
        mention={'start_block':'s0t0b0','end_block':'s0t0b0','evidence':'remove a governor for cause','document_ids':['doc']}
        resolved=validate_mentions([mention],rows,[{'id':'doc'}])[0]
        self.assertEqual((resolved['start'],resolved['end']),(12.5,20))
        with self.assertRaises(ValueError): validate_mentions([mention | {'evidence':'for incompetence'}],rows,[{'id':'doc'}])
        with self.assertRaises(ValueError): validate_mentions([mention | {'document_ids':['imaginary']}],rows,[{'id':'doc'}])


if __name__ == '__main__': unittest.main()
