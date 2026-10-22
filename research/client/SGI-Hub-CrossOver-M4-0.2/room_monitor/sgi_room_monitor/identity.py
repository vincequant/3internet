"""Room identity that survives sort changes and reused list IDs."""
import hashlib
import re

HOST_IN_NAME = re.compile(r'\[([^\]]+)\]\s*$')


def host_of(room):
    name = str(room.get('name') or '')
    match = HOST_IN_NAME.search(name)
    if match:
        return match.group(1)
    return str(room.get('host') or '')


def room_name(room):
    name = str(room.get('name') or '')
    return HOST_IN_NAME.sub('', name).strip() or name


def occupancy(room):
    """Unknown counts stay None. Never coerce a missing number to 0."""
    current = room.get('current') if room and 'current' in room else None
    maximum = room.get('maximum') if room and 'maximum' in room else None
    return (
        None if current is None else int(current),
        None if maximum is None else int(maximum),
    )


def fingerprint(room):
    body = '|'.join([
        str(room.get('id') or ''),
        room_name(room),
        host_of(room),
        str(room.get('version') or ''),
    ])
    return hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]


def same_listing(left, right):
    if not left or not right:
        return False
    if str(left.get('id') or '') and str(left.get('id')) == str(right.get('id')):
        return room_name(left) == room_name(right) and host_of(left) == host_of(right)
    return room_name(left) == room_name(right) and host_of(left) == host_of(right)


def reused_id(previous, current):
    if not previous or not current:
        return False
    if str(previous.get('id') or '') != str(current.get('id') or ''):
        return False
    return room_name(previous) != room_name(current) or host_of(previous) != host_of(current)
