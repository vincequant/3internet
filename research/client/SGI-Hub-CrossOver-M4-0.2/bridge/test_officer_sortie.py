import sys
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent / 'app'), str(Path(__file__).resolve().parent)]
from officer_sortie import (
    format_preview, kind_preview, officer_cells, kind_skill_flags, has_ambush_skill,
    pinned_skill_cells, pinned_skill_flags_from_text, remaining_skill_text, unit_has_ambush,
    recruit_share_label, roster_visible, roster_skill_flags, roster_skill_cells, ROSTER_COLORS,
    unique_place_ids, wild_city_counts,
)
from test_preparation import general, state
from unittest.mock import patch


class OfficerSortie(unittest.TestCase):
    def test_preview_uses_current_size_and_stock_cap(self):
        force = state()['entities']['lords'][0]
        g = general(1, 14000, 84, 100)
        infantry = kind_preview(g, force, 'infantry')
        self.assertEqual((infantry['size_label'], infantry['name'], infantry['factor'], infantry['power'], infantry['attack']),
                         ('小队', '步兵', 143, 92, 88))
        cavalry = kind_preview(g, force, 'cavalry')
        self.assertEqual((cavalry['soldiers'], cavalry['capped'], cavalry['name'], cavalry['factor'], cavalry['attack']),
                         (8860, True, '铁骑兵', 211, 129))
        bow = kind_preview(g, force, 'bow')
        self.assertEqual((bow['name'], bow['factor'], bow['attack']), ('强弓兵', 167, 102))
        force['troop_stock']['infantry'] = 0
        self.assertIsNone(kind_preview(g, force, 'infantry'))

    def test_mid_size_without_stock_cap(self):
        force = state()['entities']['lords'][0]
        force['troop_stock']['infantry'] = 80000
        mid = kind_preview(general(1, 25000, 84, 100), force, 'infantry')
        self.assertEqual((mid['size_label'], mid['factor'], mid['attack'], mid['capped']), ('中队', 243, 149, False))

    def test_cells_and_recommendation_text(self):
        s = state()
        g = s['entities']['generals'][0]
        cells = officer_cells(g, s['entities']['lords'][0], s)
        self.assertEqual(cells['infantry'], '88')
        self.assertEqual(cells['cavalry'], '129')
        self.assertEqual(cells['bow'], '102')
        blocked = officer_cells(g, s['entities']['lords'][0], {'build_sha256': 'other'})
        self.assertEqual(blocked, {'infantry': '—', 'cavalry': '—', 'bow': '—'})

    def test_pinned_skills_split_out_of_skill_text(self):
        self.assertEqual(pinned_skill_flags_from_text('骑马 / 弓箭 / 无双 / 奇袭'),
                         {'ride': True, 'bow': True, 'ambush': False})
        self.assertEqual(pinned_skill_cells('骑马 / 埋伏 / 无双'),
                         {'ride': '●', 'bow': '—', 'ambush': '●'})
        self.assertEqual(remaining_skill_text('骑马 / 弓箭 / 埋伏 / 无双 / 奇袭'), '无双 / 奇袭')
        self.assertEqual(remaining_skill_text('骑马 / 弓箭'), '—')
        self.assertEqual(remaining_skill_text('未匹配'), '未匹配')
        self.assertEqual(pinned_skill_cells('全技能'), {'ride': '●', 'bow': '●', 'ambush': '●'})
        self.assertEqual(remaining_skill_text('全技能'), '全技能')
        self.assertEqual(pinned_skill_flags_from_text('伏兵 / 火攻'),
                         {'ride': False, 'bow': False, 'ambush': True})

    def test_kind_skill_flags_use_listed_ride_and_bow(self):
        with patch('officer_sortie.skills_for', return_value={'骑马', '无双'}):
            self.assertEqual(kind_skill_flags({}), {'cavalry': True, 'bow': False})
        with patch('officer_sortie.skills_for', return_value={'弓箭'}):
            self.assertEqual(kind_skill_flags({}), {'cavalry': False, 'bow': True})
        with patch('officer_sortie.skills_for', return_value=set()):
            self.assertEqual(kind_skill_flags({}), {'cavalry': False, 'bow': False})

    def test_ambush_uses_matched_website_skills_only(self):
        with patch('officer_sortie.skills_for', return_value={'埋伏', '骑马'}):
            self.assertTrue(has_ambush_skill({}))
        with patch('officer_sortie.skills_for', return_value={'伏兵'}):
            self.assertTrue(has_ambush_skill({}))
        with patch('officer_sortie.skills_for', return_value={'全技能'}):
            self.assertTrue(has_ambush_skill({}))
        with patch('officer_sortie.skills_for', return_value={'骑马', '奇袭'}):
            self.assertFalse(has_ambush_skill({}))
        with patch('officer_sortie.skills_for', return_value=set()):
            self.assertFalse(has_ambush_skill({}))

    def test_unit_ambush_needs_unique_officer(self):
        state = {'entities': {'generals': [
            {'general_id_raw': 1, 'name': '甲'},
            {'general_id_raw': 2, 'name': '乙'},
            {'general_id_raw': 2, 'name': '丙'},
        ]}}
        with patch('officer_sortie.has_ambush_skill', side_effect=lambda g: g.get('general_id_raw') == 1):
            self.assertTrue(unit_has_ambush(state, {'general_ids': [1, 9]}))
            self.assertFalse(unit_has_ambush(state, {'general_ids': [2]}))
            self.assertFalse(unit_has_ambush(state, {'general_ids': [9]}))
            self.assertFalse(unit_has_ambush(state, {'general_ids': []}))

    def test_unit_label_ink_follows_ambush(self):
        from map_unit_labels import unit_label_ink
        from officer_sortie import AMBUSH_INK
        state = {'entities': {'generals': [{'general_id_raw': 1, 'name': '甲'}]}}
        with patch('officer_sortie.has_ambush_skill', return_value=True):
            self.assertEqual(unit_label_ink(state, {'general_ids': [1]}), AMBUSH_INK)
        with patch('officer_sortie.has_ambush_skill', return_value=False):
            self.assertEqual(unit_label_ink(state, {'general_ids': [1]}), '#25271e')

    def test_format_marks_stock_limit(self):
        self.assertEqual(format_preview(None), '—')
        text = format_preview({'attack': 88, 'factor': 143, 'size_label': '小队', 'name': '步兵', 'capped': True})
        self.assertEqual(text, '88')

    def test_officer_title_uses_standout_stat(self):
        from officer_reference import officer_title
        self.assertEqual(officer_title({
            'name': '黄祖',
            'attributes': {'lead': 70, 'war': 68, 'intel': 50, 'pol': 16, 'cha': 40},
        }), '黄祖(统:70)')
        self.assertEqual(officer_title({'name': '黄祖'}), '黄祖(统:70)')
        self.assertEqual(officer_title({
            'name': '禰衡',
            'attributes': {'lead': 65, 'war': 19, 'intel': 91, 'pol': 75, 'cha': 8},
        }), '禰衡(智:91)')
        self.assertEqual(officer_title({'name': '无名'}), '无名')
        from officer_reference import hire_command_text
        self.assertEqual(hire_command_text({
            'name': '张松',
            'attributes': {'lead': 63, 'war': 22, 'intel': 89, 'pol': 80, 'cha': 40},
        }, '成都'), '录用 张松(智力:89)：成都')
        from officer_reference import officer_event_text
        self.assertEqual(officer_event_text({
            'name': '邓艾',
            'attributes': {'lead': 80, 'war': 70, 'intel': 92, 'pol': 60, 'cha': 50},
        }, '庐江', '主动加入'), '加入 邓艾(智力:92)：庐江')
        self.assertEqual(officer_event_text({'name': '黄祖'}, '临晋', '主动加入'), '加入 黄祖(统武:138)：临晋')
        self.assertEqual(officer_event_text({'name': '蒯良'}, '西河', '主动加入'), '加入 蒯良(智力:88)：西河')

    def test_roster_includes_wild_and_hides_dead_unlisted_and_unnamed(self):
        forces = {1}
        keep = {'owner_raw': 1, 'status_code': 0, 'status_label': '现役'}
        self.assertTrue(roster_visible(keep, forces))
        self.assertTrue(roster_visible({**keep, 'status_code': 2, 'status_label': '出阵'}, forces))
        self.assertTrue(roster_visible({**keep, 'status_code': 4, 'status_label': '俘虏'}, forces))
        self.assertTrue(roster_visible({**keep, 'status_code': 6, 'status_label': '负伤中'}, forces))
        self.assertTrue(roster_visible({**keep, 'owner_raw': 65535, 'status_code': 1, 'status_label': '在野'}, forces))
        self.assertFalse(roster_visible({**keep, 'owner_raw': 65535, 'status_code': 5, 'status_label': '死亡'}, forces))
        self.assertFalse(roster_visible({**keep, 'owner_raw': 9, 'status_code': 0, 'status_label': '现役'}, forces))
        self.assertFalse(roster_visible({**keep, 'status_code': 5, 'status_label': '死亡'}, forces))
        self.assertFalse(roster_visible({**keep, 'status_code': 3, 'status_label': '未登场'}, forces))
        self.assertFalse(roster_visible({**keep, 'status_code': 7, 'status_label': '未命名状态'}, forces))
        hub = (Path(__file__).resolve().parents[1] / 'app' / 'omni_window.py').read_text(encoding='utf-8')
        self.assertIn('全武将含在野', hub)
        self.assertNotIn('全武将不列无归属', hub)
        self.assertIn("('recruit_share','录用参考%',90)", hub)
        self.assertIn("tag_configure('owned',background='#e3eef8')", hub)
        self.assertIn("tags=('owned',)", hub)

    def test_recruit_share_splits_wild_officers_in_one_city(self):
        wild = {'owner_raw': 65535, 'status_code': 1, 'location_city_id': 3}
        hired = {'owner_raw': 1, 'status_code': 0, 'location_city_id': 3}
        counts = wild_city_counts([wild, dict(wild), hired])
        places = unique_place_ids([{'city_id': 3}, {'city_id': 9}, {'city_id': 9}])
        self.assertEqual(counts[3], 2)
        self.assertEqual(recruit_share_label(wild, counts, places), '50.0%')
        self.assertEqual(recruit_share_label(hired, counts, places), '—')
        self.assertEqual(recruit_share_label(wild, counts, unique_place_ids([{'city_id': 9}, {'city_id': 9}])), '未知')

    def test_roster_skills_are_four_colored_tags(self):
        with patch('officer_sortie.skills_for', return_value={'骑马', '水军'}):
            flags = roster_skill_flags({})
        self.assertEqual(roster_skill_cells(flags), {'ride': '骑', 'bow': '—', 'navy': '水', 'ambush': '—'})
        with patch('officer_sortie.skills_for', return_value={'全技能'}):
            flags = roster_skill_flags({})
        self.assertEqual(roster_skill_cells(flags), {'ride': '骑', 'bow': '弓', 'navy': '水', 'ambush': '伏'})
        with patch('officer_sortie.skills_for', return_value={'伏兵'}):
            self.assertEqual(roster_skill_cells(roster_skill_flags({})), {'ride': '—', 'bow': '—', 'navy': '—', 'ambush': '伏'})
        self.assertEqual(len({bg for bg, _fg in ROSTER_COLORS.values()}), 4)
        hub = (Path(__file__).resolve().parents[1] / 'app' / 'omni_window.py').read_text(encoding='utf-8')
        filters = (Path(__file__).resolve().parents[1] / 'app' / 'talent_filters.py').read_text(encoding='utf-8')
        self.assertIn("('navy','水',40)", hub)
        self.assertNotIn("specs['all_officers'][1].extend(COLUMNS)", hub)
        self.assertNotIn('任务 / 排序', filters)
        self.assertNotIn('rolebar', filters)
        self.assertIn('skill_filter.matches', hub)
        self.assertIn('RosterSkillFilter(frame,self)', hub)

    def test_all_officer_skill_filter_uses_wild_rules(self):
        import tkinter as tk
        from types import SimpleNamespace
        from talent_filters import RosterSkillFilter, officer_has_skills
        def skills(officer):
            return set(officer.get('skills') or ())
        with patch('officer_sortie.skills_for', side_effect=skills):
            ride = {'skills': ['骑马']}
            both = {'skills': ['骑马', '埋伏']}
            self.assertTrue(officer_has_skills(ride, {'骑马'}))
            self.assertFalse(officer_has_skills(ride, {'骑马', '埋伏'}))
            self.assertTrue(officer_has_skills(ride, {'骑马', '埋伏'}, '具备任一'))
            self.assertTrue(officer_has_skills(both, {'骑马', '埋伏'}))
            self.assertTrue(officer_has_skills(ride, set()))
        root = tk.Tk()
        root.withdraw()
        calls = []
        try:
            bar = RosterSkillFilter(root, SimpleNamespace(face='PingFang SC', render_detail=lambda: calls.append(1)))
            self.assertEqual([b.cget('text') for b in bar.buttons.values()], ['骑马', '弓箭', '埋伏', '水军'])
            bar.toggle('骑马')
            self.assertEqual(bar.selected, {'骑马'})
            self.assertEqual(bar.buttons['骑马'].cget('bg'), '#1f6b45')
            self.assertIn('骑马', bar.result.cget('text'))
            self.assertEqual(calls, [1])
            bar.clear()
            self.assertEqual(bar.selected, set())
        finally:
            root.destroy()
