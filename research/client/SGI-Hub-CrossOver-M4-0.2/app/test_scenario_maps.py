"""Regional atlases stay on their own grid instead of the 101×202 sheet."""
import struct
import unittest
from pathlib import Path

from scenario_maps import MAPS, by_size, file_for, identify, match_cities
from tactical_terrain import Terrain, world_pixel
from unit_move import decode_terrain_grid

ROOT = Path(__file__).resolve().parent

# This match's cities, read while the southeast scenario was open.
SOUTHEAST_CITIES = [
    ('汝南', 30, 5), ('永安', 5, 23), ('新野', 21, 11), ('襄阳', 16, 14),
    ('江陵', 20, 28), ('长沙', 23, 54), ('零陵', 17, 73), ('武陵', 16, 44),
    ('桂阳', 25, 77), ('江夏', 27, 23), ('建业', 51, 7), ('吴县', 60, 12),
    ('会稽', 63, 25), ('寿春', 41, 3), ('庐江', 40, 25), ('柴桑', 36, 36),
    ('南海', 27, 99), ('上庸', 7, 12), ('舞阳', 7, 62), ('始新', 52, 30),
    ('章安', 64, 43), ('建安', 53, 59), ('南城', 44, 56), ('高昌', 34, 65),
    ('东安', 52, 87), ('龙川', 40, 96), ('南安', 32, 83), ('临贺', 17, 94),
    ('布山', 5, 96), ('侯官', 59, 67),
]


def _state(cities):
    return {'entities': {'cities_and_barriers': [
        {'name': name, 'world_xy_raw': [x, y]} for name, x, y in cities
    ]}}


class ScenarioMaps(unittest.TestCase):
    def test_catalog_covers_the_four_grids(self):
        self.assertEqual(by_size(101, 202)['id'], 'china')
        self.assertEqual(by_size(69, 106)['id'], 'southeast')
        self.assertEqual(by_size(101, 106)['id'], 'south')
        self.assertEqual(by_size(55, 127)['id'], 'central')
        self.assertIsNone(by_size(10, 10))
        for spec in MAPS:
            self.assertEqual(spec['pixel'], (96 * spec['width'] + 48, 24 * spec['height'] + 24))

    def test_only_verified_origins_are_recorded(self):
        self.assertEqual(by_size(101, 202)['big_origin'], (0, 0))
        self.assertEqual(by_size(69, 106)['big_origin'], (32, 96))
        self.assertIsNone(by_size(101, 106)['big_origin'])
        self.assertIsNone(by_size(55, 127)['big_origin'])

    def test_southeast_cities_do_not_select_the_big_map(self):
        state = _state(SOUTHEAST_CITIES)
        spec = identify(state)
        self.assertEqual(spec['id'], 'southeast')
        self.assertEqual(match_cities(state)['id'], 'southeast')
        px, py = world_pixel(51, 7)
        self.assertLess(px, spec['pixel'][0])
        self.assertLess(py, spec['pixel'][1])

    def test_palette_coordinates_stay_on_the_big_map(self):
        from scenario_maps import _palette_xy
        samples = list(_palette_xy().items())[:8]
        state = _state([(name, xy[0], xy[1]) for name, xy in samples])
        self.assertEqual(identify(state)['id'], 'china')

    def test_memory_size_wins_over_city_names(self):
        state = _state(SOUTHEAST_CITIES)
        state['scenario_map'] = {'known': True, 'width': 101, 'height': 202, 'id': 'china'}
        self.assertEqual(identify(state)['id'], 'china')
        state['scenario_map'] = {'known': True, 'width': 55, 'height': 127, 'id': 'central'}
        self.assertEqual(identify(state)['id'], 'central')

    def test_small_grid_is_accepted_for_movement(self):
        raw = bytes(69 * 106)
        grid = decode_terrain_grid({'terrain_grid': {'width': 69, 'height': 106, 'types': raw.hex()}})
        self.assertEqual(grid[1:], (69, 106))
        self.assertIsNone(decode_terrain_grid({'terrain_grid': {'width': 12, 'height': 12, 'types': bytes(144).hex()}}))

    def test_shipped_sheets_match_their_grids(self):
        for spec in MAPS:
            if spec['id'] == 'china':
                continue
            path = file_for(spec, 'overview')
            self.assertIsNotNone(path, spec['overview'])
            raw = path.read_bytes()
            width, height = struct.unpack_from('<ii', raw, 18)
            self.assertEqual((width, height), (spec['width'] * 3, spec['height']))
            terrain = Terrain(file_for(spec, 'mbm'), size=spec['pixel'])
            self.assertEqual(terrain.tiles_x, spec['pixel'][0] // 48)
            self.assertEqual(terrain.tile(0, 0).size, (48, 24))
            cell = world_pixel(spec['width'] - 1, spec['height'] - 1)
            self.assertLess(cell[0], spec['pixel'][0])
            self.assertLess(cell[1], spec['pixel'][1])


if __name__ == '__main__':
    unittest.main()
