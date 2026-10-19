"""P42 pre-start D8 wire: arm receipt, display-name gate, once-only gate.

The D8 body reuses the P33 codec vector own_sync_withdrawal (BE32(8)+BE32(own_id)).
The send channel ABI (0x4c80 one-arg GetHostOrSelfID + 0x4b60 four-arg reliable
submit) is SHA-bound and was proven live by P33 run-123126 (ACKed reliable
uplink) and P34 run-162501 (D8 processed, row cleared, session kept). P42 moves
the same once-only D8 to before game start: P35 run-133328 selfchecks show the
native sync state is idle (1) for the whole pre-start phase, which is the
immediate-processing branch (p34_wire.self_echo_branch).
"""
import time  # noqa: F401  (kept for the module's documented freshness semantics)


def username_authorized42(username, allow_blank_username=False):
    """Display-name gate for the pre-start smoke: 风夜 or the established fake."""
    if username in ('风夜', '小白'):
        return True
    return bool(allow_blank_username) and username == ' '


def d8_prestart_authorized(receipt, own_id, host_id, log_path, now):
    """Orchestrator-derived arm receipt bound to this run and member.

    Written only after the host watch saw this member's DLL row and the probe's
    cmd2 registration was consumed; freshness bounds keep it run-bound.
    """
    if not isinstance(receipt, dict):
        return False
    return (receipt.get('contract') == 'P42'
            and receipt.get('source') == 'p42_derived_authorization'
            and receipt.get('enable_d8_prestart') is True
            and receipt.get('own_id') == own_id
            and receipt.get('host_id') == host_id
            and receipt.get('collector_log') == str(log_path)
            and isinstance(receipt.get('observed_wall'), (int, float))
            and 0 <= now-receipt['observed_wall'] <= 600)


class P42Gate:
    """Once-only reservation; any failure ends the sequence, never retries."""

    def __init__(self):
        self.attempted = False
        self.sent = False
        self.raw_rc = None

    def attempt(self):
        if self.attempted:
            raise ValueError('p42_d8_already_attempted')
        self.attempted = True
