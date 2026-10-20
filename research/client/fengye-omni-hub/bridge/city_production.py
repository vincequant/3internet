"""SANPK 3.5 city recruitment getters, translated without calling game code.

0x434140 links building +0x16 to city +0x0a (no distance/owner filter).
0x434df9/0x434e8d/0x434f21 sum each building type's +0x18 and cap
by 0x434fb5: population < 50000 => 0; otherwise min(MulDiv(pop,1,100)*10,50000).
These are single recruitment capacities, not stock or guaranteed periodic income.
"""
KINDS = {'parade_ground': 'infantry', 'horse_farm': 'cavalry', 'bow_studio': 'bow'}

def population_cap(population):
    if type(population) is not int or population < 0:
        return None
    return 0 if population < 50000 else min(((population + 50) // 100) * 10, 50000)

def enrich_production(entities):
    buildings = entities.get('production_buildings')
    cities = entities.get('cities_and_barriers', [])
    ids = [c.get('city_id') for c in cities]
    complete = (isinstance(buildings, list) and all(
        type(b.get('linked_city_id')) is int and type(b.get('building_ui_amount')) is int
        and 0 <= b['building_ui_amount'] <= 15000 for b in buildings))
    for city in cities:
        cap = population_cap(city.get('population'))
        known = complete and city.get('type') == 'city' and cap is not None and ids.count(city.get('city_id')) == 1
        amounts = dict.fromkeys(KINDS.values())
        if known:
            for building_kind, troop_kind in KINDS.items():
                total = sum(b['building_ui_amount'] for b in buildings
                            if b.get('type') == building_kind and b['linked_city_id'] == city['city_id'])
                amounts[troop_kind] = min(total, cap)
        city['recruitment_capacity'] = {
            'amounts': amounts, 'population_cap': cap, 'unit': '人/次征兵',
            'status': 'static_engine_formula' if known else 'not_applicable' if city.get('type') != 'city' else 'unknown',
            'formula': 'min(sum(linked_buildings.amount), population<50000?0:min(round(population/100)*10,50000))',
            'scope': 'capacity_only; execution_timing_and_connectivity_not_evaluated',
        }
