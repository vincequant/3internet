import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from training_curves import ATTACK,attack_banner,current_training,curve_values,LinearScale,LogScale,calculator_attack,METRIC,tier_name
from unit_target_attack import BUILD
from website_combat import attack

class Curves(unittest.TestCase):
    def test_matches_website_calculator_and_banner(self):
        self.assertEqual(calculator_attack('bow',139,1),157)
        self.assertEqual(calculator_attack('cavalry',300,0),167)
        self.assertEqual(calculator_attack('infantry',300,0),153)
        self.assertEqual(calculator_attack('cavalry',220,0), attack('铁骑兵',0,20,100))
        self.assertEqual(tier_name('cavalry',220),'铁骑兵')
        banner = attack_banner('cavalry', 0, raw=220)
        self.assertEqual(banner['current'], 140)
        self.assertEqual(banner['full'], 167)
        self.assertEqual(attack_banner('cavalry', 0)['full'], 167)
        self.assertIsNone(attack_banner('cavalry', 0)['current'])
        source = Path(__file__).resolve().parent.parent.joinpath('app/training_curves.py').read_text(encoding='utf-8')
        self.assertIn("SEAL, SEAL_EDGE, GOLD = '#b11a1a'", source)
        self.assertIn("CURRENT, CURRENT_EDGE = '#1e5aa8'", source)
        self.assertIn('_draw_seal', source)
        self.assertEqual(curve_values('infantry',METRIC,100,100000),ATTACK['infantry'])
        self.assertGreater(curve_values('bow','每千金保守收益',100,100000)[139][0],0)
    def test_current_unknown_and_local_precedence(self):
        f={'force_id':1,'armament_raw':{'infantry':50,'cavalry':True,'bow':301}}
        s={'build_sha256':BUILD}
        self.assertEqual(current_training(s,f)[0],{'infantry':50,'cavalry':None,'bow':None})
        s.update(player_force_id=1,player_identity={'status':'confirmed','force_id':1},current_local_projection={'player_force_id':1,'armament_raw':{'bow':100}})
        self.assertEqual(current_training(s,f)[0],{'infantry':None,'cavalry':None,'bow':100})
        s['build_sha256']='unknown';self.assertTrue(all(v is None for v in current_training(s,f)[0].values()))

    def test_linear_scale_uses_full_span(self):
        scale=LinearScale([33,153])
        self.assertGreater(scale.fraction(153)-scale.fraction(33),.8)
        self.assertAlmostEqual(scale.tick(0),scale.lo)
        flat=LinearScale([150,150])
        self.assertGreater(flat.hi,flat.lo)

    def test_log_spacing_zero_and_local_zoom(self):
        scale=LogScale([100,200,400])
        self.assertAlmostEqual(scale.fraction(200)-scale.fraction(100),scale.fraction(400)-scale.fraction(200))
        local=LogScale([450,575])
        self.assertGreater(local.fraction(575)-local.fraction(450),.85)
        for scale in [local,LogScale([0,0,0],True),LogScale([0,1,20],True)]:
            for f in [0,.25,.5,1]:self.assertAlmostEqual(scale.fraction(scale.tick(f)),f)
        self.assertEqual(LogScale([0,0],True).fraction(0),0)

if __name__=='__main__':unittest.main()
