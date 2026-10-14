import sys,unittest
from datetime import datetime,date,timezone
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.discovery import calendar_groups,argument_window,argument_calendar,discover,recordings
class DiscoveryScheduleTests(unittest.TestCase):
 def test_known_recordings_skip_detail_requests(self):
  fetch=Mock(return_value='<tr><td><a href="/oral_arguments/audio/2026/25-459">25-459</a> case 10/14/26</td></tr>')
  self.assertEqual(recordings(2026,fetch,known={'2026-10-14-25-459'}),[]);self.assertEqual(fetch.call_count,1)
 def test_calendar_holiday_consolidation_and_dates(self):
  result=calendar_groups('Monday, November 30 (1) 25-183 case (2) 25-842 case Tuesday, December 1 (3) 25-246 case Wednesday, December 2 (4) 25-238) case 25-566) case Wednesday, December 9 LEGAL HOLIDAY',2026)
  self.assertEqual(result['2026-11-30'],[['25-183'],['25-842']]);self.assertEqual(result['2026-12-02'],[['25-238','25-566']]);self.assertEqual(result['2026-12-09'],[])
 def test_window_eastern_dst_and_completion(self):
  groups=[['25-1'],['25-2','25-3']]
  summer=datetime(2026,10,14,17,tzinfo=timezone.utc);winter=datetime(2026,12,2,18,tzinfo=timezone.utc)
  self.assertTrue(argument_window(summer,groups,{}));self.assertTrue(argument_window(winter,groups,{}))
  self.assertFalse(argument_window(datetime(2026,10,14,16,50,tzinfo=timezone.utc),groups,{}))
  self.assertFalse(argument_window(datetime(2026,10,14,22,10,tzinfo=timezone.utc),groups,{}))
  jobs={str(i):{'docket':d,'argument_date':'2026-10-14','audio_url':'audio','pdf_url':'pdf'} for i,d in enumerate(['25-1','25-3'])}
  self.assertFalse(argument_window(summer,groups,jobs));jobs['1']['pdf_url']='';self.assertTrue(argument_window(summer,groups,jobs))
 def test_cross_month_session(self):
  html='<a href="argument_calendars/MonthlyArgumentCalDecember2026.pdf">Session</a>'
  result=argument_calendar(date(2026,11,30),lambda _:html,lambda _:'Monday, November 30 (1) 25-183 case')
  self.assertEqual(result['groups'],[['25-183']])
 def test_session_can_continue_into_following_month(self):
  result=argument_calendar(date(2026,5,4),lambda _:'<a href="argument_calendars/MonthlyArgumentCalApril2026.pdf">Session</a>',lambda _:'Monday, May 4 (1) 25-183 case')
  self.assertEqual(result['groups'],[['25-183']])
 def test_no_published_session_means_no_fast_poll(self):
  result=argument_calendar(date(2026,7,1),lambda _:'<a href="argument_calendars/MonthlyArgumentCalApril2026.pdf">Past session</a>',Mock())
  self.assertEqual(result['groups'],[])
 def test_fast_poll_switches_back_to_normal_once_discovered(self):
  dashboard=Mock();context={'paused':False,'calendar':{'date':'2026-10-14','groups':[['25-459']]},'jobs':{}}
  def call(op,**data):
   if op=='discovery_context':return context
   if op=='discovery_claim':return False
   raise AssertionError(op)
  dashboard.call.side_effect=call;now=datetime(2026,10,14,17,tzinfo=timezone.utc)
  discover(dashboard,{'discovery':{'enabled':True}},now);self.assertEqual(dashboard.call.call_args.kwargs['seconds'],600)
  context['jobs']={'job':{'docket':'25-459','argument_date':'2026-10-14','audio_url':'a','pdf_url':'p'}}
  discover(dashboard,{'discovery':{'enabled':True}},now);self.assertEqual(dashboard.call.call_args.kwargs['seconds'],1800)
if __name__=='__main__':unittest.main()
