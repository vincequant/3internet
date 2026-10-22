import copy,unittest
from unittest.mock import patch
from test_native_unit_rules import fixture
from native_unit_rules import TERRAIN_ENCODING
from unit_move import enter_cost,move_points,terrain_kind,reachable_cells,move_brief

def state_grid():
    f=fixture();s=f['state'];raw=bytearray([255])*(101*202)
    for item in f['terrain']:
        x,y=item['xy'];raw[x*202+y]=item['code']
    s['terrain_grid']={'width':101,'height':202,'types':raw.hex(),'encoding':TERRAIN_ENCODING}
    return f,s

class NativeMovementTests(unittest.TestCase):
    def test_explicit_raid_simulation_keeps_reference_points_separate_from_live_units(self):
        from stealth_raid import sim_unit,_cost_fn
        _,s=state_grid();cell=(48,81)
        u=sim_unit(s,cell,'骑兵')
        self.assertTrue(u['movement_simulation']);self.assertEqual(move_points(s,u),18)
        self.assertTrue(reachable_cells(s,u))
        self.assertEqual(_cost_fn(s,None,False,{})(cell),2)
        u.pop('movement_simulation');self.assertIsNone(move_points(s,u))

    def test_all_35_sealed_entry_cost_discrepancies_fixed_without_pixels(self):
        f,s=state_grid();units={u['unit_id']:u for u in s['entities']['field_units']}
        with patch('unit_move._mbm_samples',side_effect=AssertionError('native terrain must not use pixels')):
            for row in f['native_cost_cases']:
                with self.subTest(row=row):
                    self.assertEqual(enter_cost(s,tuple(row['cell']),object(),units[row['unit_id']]),row['engine_entry_cost_component'])
        self.assertEqual(len(f['native_cost_cases']),35)

    def test_remaining_zero_stays_zero_not_full_turn(self):
        f,s=state_grid();u=s['entities']['field_units'][0]
        b=bytearray.fromhex(u['raw_hex']);b[0x20]=0;u['raw_hex']=b.hex()
        self.assertEqual(move_points(s,u),0)
        self.assertEqual(reachable_cells(s,u),{tuple(u['world_xy_raw']):0})
        self.assertIn('剩余移动点 0',move_brief(s,u))
        u.pop('raw_hex');u.pop('move_remaining_raw',None)
        self.assertEqual(reachable_cells(s,u),{})
        self.assertIn('未采集',move_brief(s,u))

    def test_native_codes_override_map_pixels_and_legacy15_is_unknown(self):
        _,s=state_grid();u=s['entities']['field_units'][0];cell=(40,80)
        for code,expected in ((0,3),(2,5),(15,2),(18,4),(24,None),(255,None)):
            raw=bytearray([255])*(101*202);raw[cell[0]*202+cell[1]]=code
            s['terrain_grid']['types']=raw.hex()
            with patch('unit_move._mbm_samples',side_effect=AssertionError()):
                self.assertEqual(enter_cost(s,cell,object(),u),expected)
        raw[cell[0]*202+cell[1]]=15;s['terrain_grid']['types']=raw.hex();s['terrain_grid'].pop('encoding')
        self.assertIsNone(enter_cost(s,cell,unit=u))
        self.assertEqual(terrain_kind(s,cell),'未知')

if __name__=='__main__':unittest.main()
