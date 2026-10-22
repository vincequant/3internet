"""Exercise bridge lifecycle and HTTP output without Wine or a game process."""
import copy
import io
import json
import os
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


class EndServer(Exception):
    pass


class BridgePayloadTests(unittest.TestCase):
    def run_bridge(self, collect_error=False, remote_available=False, early_error=None):
        import windows_bridge as bridge
        calls = []
        responses = {}
        now = datetime.now(timezone.utc).isoformat()
        identity = {'pid': 616, 'path': r'C:\sgi\3I\SANPK.exe', 'creation_filetime': 123}
        observed = {
            'phase': 'live', 'fresh': True, 'error': None, 'identity': identity,
            'state': {'identity': dict(identity), 'capture_end': now, 'player_context': {'slot': -1}},
        }

        class Capture:
            def __init__(self, root):
                calls.append(('construct', str(root)))

            def start(self):
                calls.append(('start',))
                if early_error == 'capture_start':
                    raise EndServer()

            def update(self, data):
                calls.append(('update', copy.deepcopy(data)))

            def close(self):
                calls.append(('close',))

            def public_status(self):
                return {'coverage': 'partial', 'events': 0, 'action_training_eligible': False}

        class Controller:
            def __init__(self, *args, **kwargs):
                pass

            def step(self):
                if collect_error:
                    raise RuntimeError('fake collector failure')
                return 1

            def public_state(self):
                return copy.deepcopy(observed)

            def release(self, **kwargs):
                calls.append(('release',))

        class Event:
            def __init__(self):
                self.stopped = False

            def is_set(self):
                return self.stopped

            def wait(self, timeout):
                self.stopped = True

            def set(self):
                self.stopped = True

        class Thread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                if self.target.__name__ == 'collect':
                    self.target()

            def join(self, timeout):
                pass

        class Recorder:
            def __init__(self, *args, **kwargs):
                pass

            def ingest(self, data):
                pass

            def close(self, *args):
                pass

            def public_status(self):
                return {'recording': False}

        class Player:
            def observe(self, data):
                return dict(data)

        class Server:
            def __init__(self, handler, port):
                self.handler = handler
                self.server_port = port

            def serve_forever(self):
                if self.server_port != 8769:
                    return
                for path in ('/health', '/api/state'):
                    handler = object.__new__(self.handler)
                    handler.path = path
                    handler.server = self
                    handler.wfile = io.BytesIO()
                    handler.send_response = lambda *args: None
                    handler.send_header = lambda *args: None
                    handler.end_headers = lambda: None
                    handler.do_GET()
                    responses[path] = json.loads(handler.wfile.getvalue())
                raise EndServer()

            def shutdown(self):
                calls.append(('server_shutdown', self.server_port))

            def server_close(self):
                calls.append(('server_close', self.server_port))

        def bind(handler):
            if early_error == 'bind':
                raise EndServer()
            return Server(handler, 8769), Server(handler, 8770) if remote_available else None

        fake_collector = types.ModuleType('collector')
        fake_collector.Collector = object
        fake_runtime = types.ModuleType('runtime_image')
        fake_runtime.configure = lambda *args: None
        read_release = bridge.Path.read_text

        def read_text(path, *args, **kwargs):
            if early_error == 'release':
                raise EndServer()
            return read_release(path, *args, **kwargs)

        with patch.dict(sys.modules, {'collector': fake_collector, 'runtime_image': fake_runtime}), \
                patch.object(bridge, 'PayloadCapture', Capture), \
                patch.object(bridge, 'RecoveryController', Controller), \
                patch.object(bridge, 'PlayerIdentity', Player), \
                patch.object(bridge, 'History', lambda *args: None), \
                patch.object(bridge, 'PlayerObservationJournal', Recorder), \
                patch.object(bridge, 'GameArchiveRecorder', Recorder), \
                patch.object(bridge, 'read_capture_config', lambda *args: None), \
                patch.object(bridge, 'attach_history', lambda data, journal: data), \
                patch.object(bridge, 'offer_war', lambda *args: None), \
                patch.object(bridge, 'bind_servers', bind), \
                patch.object(bridge.threading, 'Thread', Thread), \
                patch.object(bridge.threading, 'Event', Event), \
                patch.object(bridge.Path, 'read_text', read_text), \
                patch.dict(os.environ, {'SGI_SOURCE_ID': 'fixture', 'SGI_RUNTIME_ID': 'fake'}), \
                patch('builtins.print'):
            with self.assertRaises(EndServer):
                bridge.main()
        return calls, responses

    def test_recent_preselection_is_forwarded_and_health_exposes_only_status(self):
        calls, responses = self.run_bridge()
        updates = [item[1] for item in calls if item[0] == 'update']
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0]['phase'], 'waiting_for_player')
        self.assertFalse(updates[0]['fresh'])
        self.assertEqual(updates[0]['identity'], updates[0]['state']['identity'])
        self.assertEqual(updates[0]['source_id'], 'fixture')
        self.assertEqual(updates[0]['runtime_id'], 'fake')
        self.assertIsNone(updates[1])
        self.assertLess(calls.index(('start',)), next(i for i, item in enumerate(calls) if item[0] == 'update'))
        self.assertLess(next(i for i, item in enumerate(calls) if item == ('update', None)), calls.index(('release',)))
        self.assertEqual(calls.count(('close',)), 1)
        health = responses['/health']
        self.assertNotIn('state', health)
        self.assertEqual(health['collector_pid'], os.getpid())
        self.assertEqual(health['native_payload_observations']['coverage'], 'partial')
        self.assertFalse(health['native_payload_observations']['action_training_eligible'])
        self.assertIn('state', responses['/api/state'])
        self.assertIn(('server_close', 8769), calls)

    def test_collector_error_revokes_capture_and_shutdown_closes_it(self):
        calls, responses = self.run_bridge(collect_error=True, remote_available=True)
        self.assertEqual([item[1] for item in calls if item[0] == 'update'], [None])
        self.assertEqual(calls.count(('close',)), 1)
        self.assertEqual(responses['/health']['phase'], 'error')
        self.assertEqual(responses['/health']['error'], 'fake collector failure')
        self.assertIn(('server_shutdown', 8770), calls)
        self.assertIn(('server_close', 8770), calls)

    def test_initialization_failures_also_close_capture(self):
        for failure in ('bind', 'capture_start'):
            with self.subTest(failure=failure):
                calls, responses = self.run_bridge(early_error=failure, remote_available=True)
                self.assertEqual(calls.count(('close',)), 1)
                self.assertIn(('release',), calls)
                self.assertFalse(any(item[0] == 'update' for item in calls))
                self.assertEqual(responses, {})
                if failure == 'capture_start':
                    self.assertIn(('server_close', 8769), calls)
                    self.assertIn(('server_close', 8770), calls)

    def test_release_read_failure_happens_before_capture_is_constructed(self):
        calls, responses = self.run_bridge(early_error='release')
        self.assertEqual(calls, [])
        self.assertEqual(responses, {})


if __name__ == '__main__':
    unittest.main()
