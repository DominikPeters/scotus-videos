import re,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.alignment import find_windows,display_paragraphs,AlignmentReview

class AlignmentPolicyTests(unittest.TestCase):
 def recording(self):
  words=['token'+str(i) for i in range(1000)]
  return ' '.join(words),[{'text':word,'start':i*.5} for i,word in enumerate(words)]
 def test_sparse_recognition_still_gets_bounded_complete_fine_windows(self):
  text,recognized=self.recording();recognized=recognized[:200]+recognized[320:]
  windows,words,audit=find_windows(text,recognized,500)
  self.assertTrue(any(w['kind']=='sparse_coarse_region' and w['seconds']>35 for w in audit['warnings']))
  self.assertEqual(windows[0]['core_start'],0);self.assertEqual(windows[-1]['core_end'],len(words))
  for a,b in zip(windows,windows[1:]):self.assertEqual(a['core_end'],b['core_start'])
  self.assertTrue(all(w['audio_end']-w['audio_start']<=235 for w in windows))
 def test_limited_coverage_at_end_is_a_warning_when_window_is_bounded(self):
  text,recognized=self.recording();windows,_,audit=find_windows(text,recognized[180:],500)
  self.assertEqual(windows[0]['audio_start'],0)
  self.assertTrue(any(w['kind']=='unmatched_transcript_end' for w in audit['warnings']))
 def test_unbounded_gap_is_rejected_with_the_interval(self):
  text,recognized=self.recording()
  with self.assertRaisesRegex(AlignmentReview,'compute bound'):
   find_windows(text,recognized[:100]+recognized[800:],500)
 def test_isolated_invalid_anchor_is_discarded(self):
  text,recognized=self.recording();recognized[250]['start']=recognized[249]['start']
  _,_,audit=find_windows(text,recognized,500)
  self.assertTrue(any(w['kind']=='discarded_coarse_anchor' for w in audit['warnings']))
 def test_initial_stage_direction_uses_following_speech(self):
  text='(Laughter.) Hello there';words=list(re.finditer(r'\S+',text))
  transcript={'paragraphs':[{'text':'(Laughter.)','start_offset':0,'end_offset':11},{'text':'Hello there','start_offset':12,'end_offset':len(text)}]}
  output=[{'start':0,'end':0,'target_empty':True},{'start':2,'end':2.4,'target_empty':False},{'start':2.5,'end':3,'target_empty':False}]
  p,w=display_paragraphs(transcript,words,output,{0},4)
  self.assertEqual([x['start'] for x in p],[2,2]);self.assertEqual(p[0]['timing_policy'],'following_speech_start')
 def test_small_boundary_disagreement_is_clamped_but_large_reverse_is_held(self):
  text='Hello there';words=list(re.finditer(r'\S+',text));transcript={'paragraphs':[{'text':'Hello','start_offset':0,'end_offset':5},{'text':'there','start_offset':6,'end_offset':11}]}
  output=[{'start':2,'end':2.1,'target_empty':False},{'start':1.9,'end':2.3,'target_empty':False}]
  p,w=display_paragraphs(transcript,words,output,set(),4)
  self.assertEqual(p[1]['start'],2);self.assertEqual(w[0]['kind'],'paragraph_boundary_clamped')
  output[1]['start']=1
  with self.assertRaises(AlignmentReview):display_paragraphs(transcript,words,output,set(),4)
