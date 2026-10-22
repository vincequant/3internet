import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from training_curves import ATTACK,current_training,curve_values,LogScale
from unit_target_attack import BUILD

class Curves(unittest.TestCase):
    def test_thresholds_and_flat_infantry(self):
        self.assertEqual(ATTACK['infantry'][100],(150,250,350))
        self.assertEqual(ATTACK['infantry'][200],(190,300,400))
        self.assertEqual(ATTACK['infantry'][200],ATTACK['infantry'][300])
        self.assertEqual(ATTACK['cavalry'][100][0]-ATTACK['cavalry'][99][0],25)
        self.assertEqual(ATTACK['bow'][300],(360,460,560))
        self.assertEqual(curve_values('infantry','每千金保守收益',100,100000)[200],(0,0,0))
    def test_current_unknown_and_local_precedence(self):
        f={'force_id':1,'armament_raw':{'infantry':50,'cavalry':True,'bow':301}}
        s={'build_sha256':BUILD}
        self.assertEqual(current_training(s,f)[0],{'infantry':50,'cavalry':None,'bow':None})
        s.update(player_force_id=1,player_identity={'status':'confirmed','force_id':1},current_local_projection={'player_force_id':1,'armament_raw':{'bow':100}})
        self.assertEqual(current_training(s,f)[0],{'infantry':None,'cavalry':None,'bow':100})
        s['build_sha256']='unknown';self.assertTrue(all(v is None for v in current_training(s,f)[0].values()))

    def test_log_spacing_zero_and_local_zoom(self):
        scale=LogScale([100,200,400])
        self.assertAlmostEqual(scale.fraction(200)-scale.fraction(100),scale.fraction(400)-scale.fraction(200))
        local=LogScale([450,575])
        self.assertGreater(local.fraction(575)-local.fraction(450),.85)
        for scale in [local,LogScale([0,0,0],True),LogScale([0,1,20],True)]:
            for f in [0,.25,.5,1]:self.assertAlmostEqual(scale.fraction(scale.tick(f)),f)
        self.assertEqual(LogScale([0,0],True).fraction(0),0)

if __name__=='__main__':unittest.main()
