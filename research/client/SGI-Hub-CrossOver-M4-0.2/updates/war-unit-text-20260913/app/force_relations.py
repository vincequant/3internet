"""War highlights are relative to confirmed player identity, never UI selection."""
from player_view import player_id
WAR_BACKGROUND = '#f8d9d9'
WAR_FOREGROUND = '#862e2e'
LABELS = {0: '通常', 1: '与我军战争', 2: '不可侵', 3: '同盟'}

def relation_to_player(state, force_id):
    own = player_id(state)
    if own is None or type(force_id) is not int or force_id == own or not 0 <= force_id < 22:
        return None
    forces = (state or {}).get('entities', {}).get('lords', [])
    players = [f for f in forces if f.get('force_id') == own]
    if len(players) != 1 or sum(f.get('force_id') == force_id for f in forces) != 1:
        return None
    values = players[0].get('diplomacy_relations')
    if not isinstance(values, list) or len(values) != 22:
        return None
    value = values[force_id]
    return value if type(value) is int and value in LABELS else None

def at_war(state, force_id):
    return relation_to_player(state, force_id) == 1
