"""Exclude confirmed barrier residents from current wild recruitment views.

Use live location IDs and entity types, never officer names or cached exclusions.
Unknown/ambiguous locations remain unknown; they are not assumed to be barriers.
The complete officer database is not altered.
"""
from collections import Counter


def wild_location_groups(state):
    entities = state.get('entities', {})
    places = entities.get('cities_and_barriers', [])
    counts = Counter(c.get('city_id') for c in places if type(c.get('city_id')) is int)
    kinds = {c['city_id']: c.get('type') for c in places
             if type(c.get('city_id')) is int and counts[c['city_id']] == 1}
    visible, barriers = [], []
    for officer in entities.get('generals', []):
        if officer.get('status_code') != 1 or officer.get('owner_raw') != 65535:
            continue
        location = officer.get('location_city_id')
        is_barrier = type(location) is int and kinds.get(location) == 'barrier'
        (barriers if is_barrier else visible).append(officer)
    return visible, barriers
