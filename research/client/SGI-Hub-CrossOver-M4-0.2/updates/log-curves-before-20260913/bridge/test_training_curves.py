import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from training_curves import ATTACK,current_training,curve_values
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

if __name__=='__main__':unittest.main()
