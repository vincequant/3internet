import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from force_unit_tour import (
    UNIT_TOUR_ZOOM, force_field_units, page_key_delta, retained_locator_zoom, step_index,
    tour_caption, tour_title, unit_page_index,
)
from panorama_model import MIN_ZOOM


def _state():
    return {
        'entities': {
            'lords': [{'force_id': 0, 'name': '魏'}, {'force_id': 18, 'name': '巴'}],
            'generals': [
                {'general_id_raw': 191, 'name': '诸葛亮'},
                {'general_id_raw': 399, 'name': '文丑'},
                {'general_id_raw': 818, 'name': 'OK哥'},
            ],
            'field_units': [
                {'unit_id': 1, 'unit_kind': '强化步兵', 'owner_raw': 0, 'world_xy_raw': [57, 67],
                 'soldiers_candidate': 5711, 'general_ids': [191, None, None]},
                {'unit_id': 11, 'unit_kind': '强弓兵', 'owner_raw': 0, 'world_xy_raw': [38, 86],
                 'soldiers_candidate': 4500, 'general_ids': [399, None, None]},
                {'unit_id': 2, 'unit_kind': '强化骑兵', 'owner_raw': 18, 'world_xy_raw': [39, 109],
                 'soldiers_candidate': 3157, 'general_ids': [818, None, None]},
            ],
            'cities_and_barriers': [],
        }
    }


class ForceUnitTourTests(unittest.TestCase):
    def test_pages_one_force_in_field_order(self):
        state = _state()
        wei = force_field_units(state, 0)
        self.assertEqual([row['unit_id'] for row in wei], [1, 11])
        self.assertEqual(unit_page_index(wei, {'unit_id': 11}), 1)
        self.assertEqual(step_index(2, 1, 1), 0)
        self.assertIn('1/2', tour_caption(state, wei, 0))
        self.assertIn('魏', tour_caption(state, wei, 0))
        self.assertIn('(57,67)', tour_caption(state, wei, 0))
        self.assertIn('2/2', tour_title(state, wei, 1))
        self.assertEqual(force_field_units(state, 18)[0]['unit_id'], 2)
        self.assertEqual(force_field_units(state, None), [])

    def test_hub_and_panorama_open_the_pager(self):
        hub = (ROOT / 'app/omni_window.py').read_text(encoding='utf-8')
        panorama = (ROOT / 'app/panorama_map.py').read_text(encoding='utf-8')
        self.assertIn('show_force_unit_tour', hub)
        self.assertIn('_tour_from_table', hub)
        self.assertIn("bind('<ButtonRelease-1>'", hub)
        self.assertIn('on_tour_unit', panorama)
        self.assertIn('_open_unit_tour', panorama)

    def test_pager_defaults_to_national_map_and_arrow_pages(self):
        self.assertEqual(UNIT_TOUR_ZOOM, MIN_ZOOM)
        self.assertEqual(page_key_delta('Right'), 1)
        self.assertEqual(page_key_delta('Left'), -1)
        self.assertEqual(page_key_delta('Up'), 0)
        self.assertEqual(retained_locator_zoom(9.5, True, UNIT_TOUR_ZOOM), 9.5)
        self.assertEqual(retained_locator_zoom(9.5, False, UNIT_TOUR_ZOOM), MIN_ZOOM)
        pager = (ROOT / 'app/force_unit_pager.py').read_text(encoding='utf-8')
        self.assertIn('keep_zoom=True', pager)
        self.assertIn('default_zoom=UNIT_TOUR_ZOOM', pager)
        self.assertIn('_bind_page_keys', pager)
        self.assertIn("widget.bind('<Left>'", pager)
        self.assertIn("widget.bind('<Right>'", pager)


if __name__ == '__main__':
    unittest.main()
