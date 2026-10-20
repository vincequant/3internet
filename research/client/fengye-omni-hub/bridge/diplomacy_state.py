"""SANPK 3.5 relation getter 0x467b82, label switch 0x42048d.

lord+0x32 stores 22 relation bytes indexed by the other force's ID.
The diplomacy UI takes the current player's row (0x445c8a..0x445e0a).
State 1 means war; it does not identify who initiated the declaration.
"""
def decode_relations(raw):
    if len(raw) < 0x48:
        return None
    return [v if v in (0, 1, 2, 3) else None for v in raw[0x32:0x48]]
