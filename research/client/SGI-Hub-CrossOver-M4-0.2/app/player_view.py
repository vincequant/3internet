"""All views consume the bridge's single, explicitly confirmed player identity."""
def player_id(state):
    meta = (state or {}).get('player_identity') or {}
    fid = (state or {}).get('player_force_id')
    return fid if type(fid) is int and meta.get('status') == 'confirmed' and meta.get('force_id') == fid else None


def local_projection(state, force_id):
    p = (state or {}).get('current_local_projection') or {}
    if player_id(state) is not None and player_id(state) == force_id and p.get('player_force_id') == force_id:
        return p
    return None


def comparison_ids(state, selected):
    return list(dict.fromkeys(fid for fid in (player_id(state), selected) if fid is not None))
