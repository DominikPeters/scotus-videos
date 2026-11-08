import subprocess
from pathlib import Path
import unittest

class IntroTests(unittest.TestCase):
 def test_opening_card_animation_does_not_shorten_splash(self):
  subprocess.run(['node',str(Path(__file__).with_name('intro.cjs'))],check=True,capture_output=True,text=True)
