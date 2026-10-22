import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from force_relations import unit_row_tags, WAR_UNIT_TAG, WAR_UNIT_FOREGROUND
from force_name_colors import FactionCells

def state():
    relations=[0]*22;relations[19]=1
    return {'player_force_id':20,'player_identity':{'status':'confirmed','force_id':20},
            'entities':{'lords':[{'force_id':20,'diplomacy_relations':relations},{'force_id':19},{'force_id':1}]}}

class WarUnitText(unittest.TestCase):
    def test_only_warring_units_preserve_distance_background_tag(self):
        s=state()
        for base in ('','near','middle','unit_far','unit_near5'):
            tags=unit_row_tags(s,{'owner_raw':19},'field_units',base)
            self.assertIn(WAR_UNIT_TAG,tags)
            if base:self.assertEqual(tags[0],base)
        for source in ('cities_and_barriers','production_buildings','traps','force_units'):
            self.assertNotIn(WAR_UNIT_TAG,unit_row_tags(s,{'owner_raw':19},source,'middle'))
        for owner in (20,1,None,65535):
            self.assertNotIn(WAR_UNIT_TAG,unit_row_tags(s,{'owner_raw':owner},'field_units','near'))

    def test_peace_and_unknown_identity_remove_red(self):
        s=state();s['entities']['lords'][0]['diplomacy_relations'][19]=2
        self.assertEqual(unit_row_tags(s,{'owner_raw':19},'field_units','middle'),('middle',))
        s=state();s['player_identity']['status']='unknown'
        self.assertEqual(unit_row_tags(s,{'owner_raw':19},'field_units'),())

    def test_selected_war_cells_keep_red_and_only_faction_spans_keep_color(self):
        tree=MagicMock();tree.winfo_exists.return_value=True;tree.winfo_width.return_value=500
        tree.cget.return_value='Treeview';tree.get_children.return_value=['0'];tree.bbox.return_value=(1,1,100,20)
        tree.__getitem__.return_value=('name','owner','detail')
        tree.set.side_effect=lambda key,col: {'name':'晋','owner':'晋','detail':'部队信息'}[col]
        tree.selection.return_value=('0',);tree.item.return_value=('middle',WAR_UNIT_TAG)
        tree.tag_configure.side_effect=lambda tag,option:'#fff0bd' if tag=='middle' else ''
        manager=Mock();manager.spans.side_effect=lambda text:[(0,len(text),19)]
        obj=FactionCells.__new__(FactionCells);obj.tree=tree;obj.manager=manager;obj.cells={}
        font=Mock();font.metrics.return_value=12
        with patch('force_name_colors.ttk.Style'),patch('force_name_colors.tkfont.Font',return_value=font),patch('force_name_colors.tk.Canvas') as canvas:
            canvas.side_effect=lambda *a,**kw:Mock()
            obj.paint()
            calls=manager.draw_text.call_args_list
            self.assertEqual(len(calls),3)
            self.assertEqual([c.args[-1] for c in calls],[[],[(0,1,19)],[]])
            self.assertTrue(all(c.args[-2]==WAR_UNIT_FOREGROUND for c in calls))
            for cell in obj.cells.values():cell.configure.assert_called_with(bg='#fff0bd')
            old=obj.cells[('0','detail')]
            # Peace refresh discards the extra red overlays, while the faction
            # name overlay still follows its usual color rules.
            tree.item.return_value=('middle',);manager.spans.side_effect=lambda text:[(0,1,19)] if text=='晋' else []
            obj.paint();old.destroy.assert_called_once()

    def test_ambush_name_and_unit_cells_use_dark_yellow(self):
        from officer_sortie import AMBUSH_INK
        tree=MagicMock();tree.winfo_exists.return_value=True;tree.winfo_width.return_value=500
        tree.cget.return_value='Treeview';tree.get_children.return_value=['0'];tree.bbox.return_value=(1,1,100,20)
        tree.__getitem__.return_value=('kind','generals','owner')
        tree.set.side_effect=lambda key,col:{'kind':'骑兵','generals':'张合','owner':'晋'}[col]
        tree.selection.return_value=();tree.item.return_value=('unit_near5',WAR_UNIT_TAG,'ambush_text')
        tree.tag_configure.side_effect=lambda tag,option:'#f8d6d3' if tag=='unit_near5' else ''
        manager=Mock();manager.spans.return_value=[]
        obj=FactionCells.__new__(FactionCells);obj.tree=tree;obj.manager=manager;obj.cells={}
        font=Mock();font.metrics.return_value=12
        with patch('force_name_colors.ttk.Style'),patch('force_name_colors.tkfont.Font',return_value=font),patch('force_name_colors.tk.Canvas') as canvas:
            canvas.side_effect=lambda *a,**kw:Mock()
            obj.paint()
            colors=[c.args[-2] for c in manager.draw_text.call_args_list]
            self.assertEqual(colors,[AMBUSH_INK,AMBUSH_INK,WAR_UNIT_FOREGROUND])

if __name__=='__main__':unittest.main()
