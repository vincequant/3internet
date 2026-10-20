"""Explicitly paired, independently verified command evidence from a second Mac.

Never infer a match from equal dates/force names. A machine-local pairing must
name both exact process bindings and capture-player sessions. The selected
world snapshot, original journals and training labels are never changed.
"""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import time
import urllib.request

from connection import Connection, ROOT
from command_transport import import_commands, validate_row, MAX_TRANSFER
from native_command_evidence import _binding, MAX_ROWS, MAX_LINE


def scope(payload):
    return dict(binding=_binding(payload),
                player_session_id=((payload.get('state') or {}).get('player_identity') or {}).get('session_id'))


class CommandPeer:
    def __init__(self, root=ROOT, fetch=None):
        self.root=Path(root);self.fetch=fetch;self.connection=None
        self.config=None;self.saved=None;self.last_poll=0;self.wire_rows={}
        path=self.root/'command-peer.local.json'
        if not path.exists():return
        try:
            cfg=json.loads(path.read_text(encoding='utf8'))
            if (cfg.get('schema')!=1 or cfg.get('confirmed_same_game') is not True
                    or not all(cfg[k].get('player_session_id') for k in ('primary','peer'))
                    or cfg['primary']['binding']['source_id']==cfg['peer']['binding']['source_id']):
                return
            self.config=cfg;self.connection=Connection(cfg['connection'])
            self.cache=self.root/'command-peer-cache'/(hashlib.sha256(json.dumps(cfg['peer'],sort_keys=True).encode()).hexdigest()[:20]+'.json')
            self._load()
        except (OSError,ValueError,KeyError,TypeError):return

    def _load(self):
        if not self.cache.exists() or self.cache.stat().st_size>MAX_TRANSFER+65536:return
        data=json.loads(self.cache.read_bytes())
        if data.get('schema')!=1 or data.get('scope')!=self.config['peer']:return
        wire=data['rows']
        if not isinstance(wire,list) or len(wire)>MAX_ROWS:return
        rows=[]
        for row in wire:
            encoded=row['source_line_b64']
            if type(encoded) is not str or len(encoded)>((MAX_LINE+2)//3)*4:return
            rows.append(validate_row(row,self.config['peer']['binding'],base64.b64decode(encoded,validate=True)))
        self.wire_rows={self._key(r):r for r in wire}
        self.saved=dict(binding=deepcopy(self.config['peer']['binding']),rows=rows,
                        complete_command_stream=False,process_scope_only=True,
                        capture_status={'phase':'waiting','error':'retained_peer'})

    @staticmethod
    def _key(row):return row['queue_entry_hex'],row['raw_sha256']

    def _remember(self, peer, evidence):
        incoming=(peer['state']['native_command_transfer'])['rows']
        for row in incoming:
            self.wire_rows[self._key(row)]=deepcopy(row)
        wire=sorted(self.wire_rows.values(),key=lambda r:r['observed_at'])[-MAX_ROWS:]
        self.wire_rows={self._key(r):r for r in wire}
        result=dict(evidence,rows=[validate_row(r,self.config['peer']['binding'],
                    base64.b64decode(r['source_line_b64'],validate=True)) for r in wire])
        raw=json.dumps(dict(schema=1,scope=self.config['peer'],rows=wire),ensure_ascii=True).encode()
        if len(raw)>MAX_TRANSFER+65536:raise ValueError('peer cache too large')
        self.cache.parent.mkdir(exist_ok=True)
        temp=self.cache.with_suffix('.tmp');temp.write_bytes(raw);temp.replace(self.cache)
        self.saved=result

    def close(self):
        if self.connection:self.connection.close()

    def attach(self, payload, commands):
        if not self.config or payload.get('fresh') is not True or payload.get('error'):
            return commands
        try:
            if scope(payload)!=self.config['primary']:return commands
        except (ValueError,KeyError,TypeError):return commands
        now=time.monotonic()
        if now-self.last_poll>=2:
            self.last_poll=now
            try:
                if self.fetch:peer=self.fetch()
                else:
                    self.connection.ensure()
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                            self.connection.base_url+'/api/state',timeout=1) as response:
                        raw=response.read(8*1024*1024+1)
                    if len(raw)>8*1024*1024:raise ValueError('peer response too large')
                    peer=json.loads(raw);self.connection.validate(peer)
                if scope(peer)!=self.config['peer']:raise ValueError('peer game scope changed')
                evidence=import_commands(peer)
                if evidence['status']!='partial_native_queue_evidence':raise ValueError('peer evidence unavailable')
                # The source exporter merges retained originals. Keep this
                # complete verified batch in memory during temporary outages.
                self._remember(peer,evidence)
            except (OSError,ValueError,KeyError,TypeError):
                if self.saved:
                    self.saved=dict(self.saved,capture_status={'phase':'waiting','error':'peer_offline'})
        if not self.saved:return commands
        result=dict(commands)
        result['supplemental_sources']=[deepcopy(self.saved)]
        return result
