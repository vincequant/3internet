import sys
import unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).resolve().parents[1]/'bridge')]
from city_production import population_cap as engine_population_cap
from recruitment_summary import cities_over_produce,cities_over_produce_score,city_card_text,city_produce_amount,city_produce_score,city_recruit_rows,format_recruit_cell,format_recruit_display,mix_after_recruit,population_cap,predicted_after_summer,recruit_raw,recruit_view
from training_prediction import describe_stock_efficiency,efficiency_ratio,stock_bracket,stock_training_base
from world_cities import city_values

class TrainingEfficiency(unittest.TestCase):
 def test_summer_mix_matches_wei_song(self):
  self.assertEqual(recruit_raw(300),180)
  self.assertEqual(recruit_raw(190),114)
  samples=(
   (30000,190,37940,147),(10000,130,6500,109),(20000,130,1500,126),
   (30000,200,500,198),(10000,100,1000,96),(20000,180,29120,137),
   (67940,147,38750,125),(16500,109,16190,87),(21500,126,11470,108),
   (30500,300,500,298),(11000,96,7350,80),(49120,242,28480,206),
   (30000,190,41890,145),(10000,130,6500,109),(20000,130,1500,126),
   (30000,200,23190,165),(10000,100,1000,96),(20000,180,12870,151),
  )
  for stock,raw,added,after in samples:
   pred=mix_after_recruit(raw,stock,added)
   self.assertEqual(pred['raw'],after, (raw,stock,added))
   self.assertEqual(pred['stock'],stock+added)
  self.assertEqual(mix_after_recruit(190,30000,0)['raw'],190)
  self.assertIsNone(mix_after_recruit(190,30000,None))
  from military_summary import MilitarySummary
  text=MilitarySummary._after_text(None,'infantry',190,30000,{'known':41890,'missing':0})
  self.assertEqual(text,'71,890 · 强化步兵 45/100')
  self.assertNotIn('新兵原值', (Path(__file__).resolve().parents[1]/'app'/'military_summary.py').read_text(encoding='utf-8'))
  pred=predicted_after_summer(
   {'warehouse':25060,'field':12361,'total':37421,'raw':292},41890)
  self.assertEqual(pred['stock'],79311)
  self.assertEqual(pred['raw'],(292*25060+175*41890)//(25060+41890))
  self.assertEqual(pred['recruit_raw'],175)
  hold=predicted_after_summer({'warehouse':20500,'total':20500,'raw':148},0)
  self.assertEqual(hold['stock'],20500)
  self.assertEqual(hold['raw'],148)

 def test_stock_brackets(self):
  self.assertEqual(stock_training_base(9999),10)
  self.assertEqual(stock_training_base(10000),9)
  self.assertEqual(stock_training_base(28510),9)
  self.assertEqual(stock_training_base(30000),8)
  self.assertEqual(stock_training_base(100000),5)
  self.assertEqual(stock_bracket(28510)['percent'],90)
  self.assertEqual(stock_bracket(28510)['remain'],1490)
  self.assertIn('90%',describe_stock_efficiency(28510))
  self.assertIn('再募1,490人→80%',describe_stock_efficiency(28510))
  self.assertIn('已是最低档',describe_stock_efficiency(100000))
  self.assertEqual(describe_stock_efficiency(None),'未知')
  self.assertEqual(efficiency_ratio(28510),'90%')
  self.assertEqual(efficiency_ratio(None),'未知')
  page=(Path(__file__).resolve().parents[1]/'app'/'military_summary.py').read_text(encoding='utf-8')
  self.assertNotIn('攻击基值', page)
  self.assertIn('def paint_training', page)
  self.assertIn('GRADE_FG[tier]', page)

 def test_engine_cap_matches_city_production(self):
  for pop in (49999,50000,50049,50050,156500,432902,1000000):
   self.assertEqual(population_cap(pop),engine_population_cap(pop))

 def test_same_cap_does_not_share_remain(self):
  # 汝南-shaped: infantry camps nearly fill the cap; cavalry remain stays the full cap
  self.assertEqual(format_recruit_cell(13530,13600),'70')
  self.assertEqual(format_recruit_cell(0,13600),'13,600')
  self.assertEqual(format_recruit_display(13530,13600),'70 · 已建13,530')
  self.assertEqual(format_recruit_display(0,13600),'13,600 · 已建0')

 def test_city_recruit_cap_and_overflow(self):
  self.assertEqual(format_recruit_cell(500,20680),'20,180')
  self.assertEqual(format_recruit_cell(21670,15650),'溢6,020')
  state={'entities':{'lords':[{'force_id':0,'name':'魏'}],'cities_and_barriers':[
    {'type':'city','owner_raw':0,'city_id':12,'name':'许昌','population':432902,'world_xy_raw':[0,0],
     'recruitment_capacity':{'population_cap':43290,'amounts':{'infantry':500,'cavalry':6000,'bow':500}}},
    {'type':'city','owner_raw':1,'city_id':20,'name':'商丘','population':156500,'world_xy_raw':[1,1],
     'recruitment_capacity':{'population_cap':15650,'amounts':{'infantry':0,'cavalry':0,'bow':15650}}}],
   'production_buildings':[
    {'type':'parade_ground','linked_city_id':12,'building_ui_amount':500},
    {'type':'horse_farm','linked_city_id':12,'building_ui_amount':6000},
    {'type':'bow_studio','linked_city_id':12,'building_ui_amount':500},
    {'type':'bow_studio','linked_city_id':20,'building_ui_amount':11270},
    {'type':'bow_studio','linked_city_id':20,'building_ui_amount':10400}]}}
  wei=city_recruit_rows(state,0)
  self.assertEqual(len(wei),1)
  self.assertEqual(wei[0]['cap'],43290)
  self.assertEqual(wei[0]['cells']['cavalry'],'37,290')
  song=city_recruit_rows(state,1)
  self.assertEqual(song[0]['cells']['bow'],'溢6,020')
  self.assertEqual(song[0]['built']['bow'],21670)
  barrier=recruit_view(state,{'type':'barrier','name':'阳平关','population':0})
  self.assertEqual(barrier['cap_text'],'—')
  self.assertEqual(barrier['cells']['infantry'],'—')
  self.assertEqual(recruit_view(state,state['entities']['cities_and_barriers'][0])['cells']['cavalry'],'37,290')
  values=city_values(state,state['entities']['cities_and_barriers'][0])
  self.assertEqual(values[6],'432,902')
  self.assertEqual(values[7],'43,290')

 def test_cities_over_produce_strict_greater(self):
  state={'entities':{'cities_and_barriers':[
    {'type':'city','city_id':12,'name':'许昌','world_xy_raw':[57,89],
     'recruitment_capacity':{'amounts':{'infantry':500,'cavalry':6500,'bow':500}}},
    {'type':'city','city_id':20,'name':'商丘','world_xy_raw':[1,1],
     'recruitment_capacity':{'amounts':{'infantry':0,'cavalry':0,'bow':4000}}},
    {'type':'barrier','city_id':9,'name':'武关'}],
   'production_buildings':[]}}
  self.assertEqual(city_produce_amount(state,state['entities']['cities_and_barriers'][0],'cavalry'),6500)
  self.assertEqual([c['name'] for c in cities_over_produce(state,'cavalry',5000)],['许昌'])
  self.assertEqual(cities_over_produce(state,'cavalry',6500),[])
  self.assertEqual([c['name'] for c in cities_over_produce(state,'bow',3000)],['商丘'])
  self.assertEqual(city_produce_score(state,state['entities']['cities_and_barriers'][0]),20500)
  self.assertEqual(city_produce_score(state,state['entities']['cities_and_barriers'][1]),4000)
  self.assertEqual([c['name'] for c in cities_over_produce_score(state,20000)],['许昌'])
  self.assertEqual(cities_over_produce_score(state,20500),[])
  card=city_card_text(state,state['entities']['cities_and_barriers'][0])
  self.assertIn('可产骑 6,500',card)
  self.assertIn('总分(步1骑3弓1) 20,500',card)
  self.assertEqual(city_card_text(state,state['entities']['cities_and_barriers'][2]),'关隘无夏季募兵。')

if __name__=='__main__':
 unittest.main()
