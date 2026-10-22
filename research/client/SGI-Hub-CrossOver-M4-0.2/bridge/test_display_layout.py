import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from display_layout import settings
class DisplayTests(unittest.TestCase):
 def test_other_mac_fits(self):
  scale,w,h=settings(1470,956);self.assertEqual(scale,.85);self.assertLess(w,1470);self.assertLess(h+38,891)
 def test_original_mac_unchanged_density(self):self.assertEqual(settings(1710,1107),(1.,1280,900))
 def test_manual_scale(self):self.assertEqual(settings(1470,956,'80%')[0],.8)
 def test_invalid_scale_uses_auto(self):self.assertEqual(settings(1470,956,'bad')[0],.85)
