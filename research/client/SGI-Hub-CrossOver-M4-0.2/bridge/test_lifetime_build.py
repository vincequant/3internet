import hashlib
import unittest
from unittest.mock import patch
import collector
import runtime_image


class BuildCompatibility(unittest.TestCase):
    def test_exact_builds_only(self):
        self.assertTrue(collector.supported_build(collector.BUILD))
        self.assertTrue(collector.supported_build(collector.LIFETIME_HOTFIX_BUILD))
        self.assertTrue(collector.supported_build(collector.DIAGNOSTIC_HOTFIX_BUILD))
        self.assertTrue(collector.supported_build(collector.FINALIZE_HOTFIX_BUILD))
        self.assertTrue(collector.supported_build(collector.NETWORK_HOTFIX_BUILD))
        self.assertFalse(collector.supported_build('0'*64))
        self.assertFalse(collector.supported_build(collector.LIFETIME_HOTFIX_BUILD[:-1]+'0'))

    def test_unknown_build_rejected_before_module_access(self):
        with patch.object(runtime_image.Path,'read_bytes',return_value=b'unknown'), \
             patch.object(runtime_image,'module_base') as lookup:
            with self.assertRaisesRegex(RuntimeError,'SANPK'):
                runtime_image.configure(1,'test.exe')
            lookup.assert_not_called()


if __name__=='__main__':unittest.main()
