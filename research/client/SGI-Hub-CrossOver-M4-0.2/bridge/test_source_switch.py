import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'app'))
from connection import load_config, select_source, Connection, local_config

class SourceSwitchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name)/'connection.local.json'
  self.env=patch.dict(os.environ,SGI_CONNECTION_CONFIG=str(self.path));self.env.start();self.addCleanup(self.env.stop)
  base=dict(mode='remote',port=18769,ssh_host='::1',ssh_user='viewer',identity_file='key',known_hosts='hosts',expected_source='mac',label='Mac')
  self.data={'sources':{'Mac':base,'Windows':dict(base,ssh_port=2222,expected_source='windows',label='Windows')},'selected_source':'Mac'}
  self.save()
 def save(self):self.path.write_text(json.dumps(self.data))
 def test_persist_switch_and_keep_profiles(self):
  self.assertEqual(load_config()['expected_source'],'mac')
  before=self.path.read_bytes();select_source('Windows')
  cfg=load_config();self.assertEqual(cfg['ssh_port'],2222);self.assertEqual(cfg['expected_source'],'windows')
  self.assertEqual(self.path.read_bytes(),before)
  select_source('Mac');self.assertEqual(load_config()['ssh_port'],22)
 def test_unknown_rejected_and_local_supported(self):
  with self.assertRaises(ValueError):select_source('bad')
  self.data['sources']['Mac']['mode']='local';self.save()
  self.assertEqual(load_config()['mode'],'local')
  select_source('Windows');self.assertEqual(local_config()['mode'],'local')
 def test_port_rejected(self):
  self.data['sources']['Mac']['ssh_port']=0;self.save()
  with self.assertRaises(ValueError):load_config()
 def test_identity_and_readonly_required(self):
  c=Connection(load_config());p=dict(protocol_version=1,service='sgi-crossover-bridge-1',source_id='windows',read_only_endpoint=True)
  with self.assertRaises(ValueError):c.validate(p)
  p.update(source_id='mac',read_only_endpoint=False)
  with self.assertRaises(ValueError):c.validate(p)
  p['read_only_endpoint']=True;c.validate(p)
 def test_reuse_healthy_forward(self):
  c=Connection(load_config())
  health=dict(protocol_version=1,service='sgi-crossover-bridge-1',source_id='mac',read_only_endpoint=True)
  with patch.object(c,'_port_open',return_value=True), patch.object(c,'_probe_forward',return_value=health):
   c.ensure()
   self.assertIsNone(c.process)
  with patch.object(c,'_port_open',return_value=True), patch.object(c,'_probe_forward',return_value=None):
   with self.assertRaises(ConnectionError) as error:
    c.ensure()
   self.assertIn('端口已占用', str(error.exception))
