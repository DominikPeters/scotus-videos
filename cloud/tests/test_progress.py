import json,subprocess,unittest
from pathlib import Path

class ProgressTests(unittest.TestCase):
    def split(self,duration,width,audio_start=0,event_start=0,event_end=200):
        helper=Path(__file__).resolve().parents[1]/'render/progress.js'
        script='const {splitProgressEvent}=require('+json.dumps(str(helper))+');console.log(JSON.stringify(splitProgressEvent('+json.dumps({'ops':[{'name':'nextTextBlock'}],'first_frame':event_start,'end_frame':event_end})+','+json.dumps({'section':0,'interaction':1,'start':0,'end':duration,'width':width})+','+str(audio_start)+')));'
        return json.loads(subprocess.check_output(['node','-e',script]))

    def test_pixel_schedule_and_interval_limits(self):
        for duration,width,frames in ((20,100,10),(60,100,24),(120,100,48),(300,100,60),(60,66,36)):
            events=self.split(duration,width)
            self.assertEqual(events[0]['end_frame'],frames)

    def test_preserves_timeline_operations_and_audio_clock(self):
        events=self.split(60,100,audio_start=15,event_start=400,event_end=467)
        self.assertEqual([(e['first_frame'],e['end_frame']) for e in events],[(400,424),(424,448),(448,467)])
        self.assertEqual(events[0]['ops'][0]['name'],'nextTextBlock')
        self.assertEqual(events[0]['ops'][-1]['args'][-1],25)
        self.assertEqual(events[1]['ops'][0]['args'][-1],27)
        self.assertTrue(all(len(e['ops'])==1 for e in events[1:]))

    def test_clamps_progress_and_keeps_zero_duration_operations(self):
        self.assertEqual(self.split(60,100,audio_start=90)[0]['ops'][-1]['args'][-1],100)
        events=self.split(60,100,event_start=20,event_end=20)
        self.assertEqual(events,[{'ops':[{'name':'nextTextBlock'}],'first_frame':20,'end_frame':20}])
