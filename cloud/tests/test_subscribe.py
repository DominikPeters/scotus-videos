import subprocess,unittest
from pathlib import Path

class SubscribeTests(unittest.TestCase):
 def test_card_free_scheduling_and_deterministic_capture(self):
  subprocess.run(['node',str(Path(__file__).with_name('subscribe.cjs'))],check=True,capture_output=True,text=True)
