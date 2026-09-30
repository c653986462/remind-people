import importlib.util
from pathlib import Path
import unittest


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


order = load('check-release-order')
desktop = load('check-desktop-target')


class PublicationGuardTests(unittest.TestCase):
    def test_bootstrap_and_manual_server_release_can_be_upgraded(self):
        order.check({'run_number': '7'}, {})

    def test_newer_and_same_ci_run_are_allowed(self):
        old = {'run_number': '7', 'run_id': '100', 'source_commit': 'a' * 40}
        order.check(old, old)
        order.check({**old, 'run_number': '8'}, old)

    def test_older_or_ambiguous_ci_run_is_rejected(self):
        old = {'run_number': '7', 'run_id': '100', 'source_commit': 'a' * 40}
        for candidate in [{}, {**old, 'run_number': '6'}, {**old, 'run_id': '101'}, {**old, 'source_commit': 'b' * 40}]:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                order.check(candidate, old)

    def test_matching_desktop_source_and_retry_are_allowed(self):
        candidate = {'run_id': '100', 'source_commit': 'a' * 40, 'version': '0.1.18'}
        active = {'run_id': '100', 'source_commit': 'a' * 40}
        desktop.check(candidate, active, 'version: 0.1.11\n')
        desktop.check(candidate, active, 'version: 0.1.18\n')

    def test_missing_or_wrong_web_run_blocks_desktop(self):
        candidate = {'run_id': '100', 'source_commit': 'a' * 40, 'version': '0.1.18'}
        for active in [{}, {'run_id': '101', 'source_commit': 'a' * 40}, {'run_id': '100', 'source_commit': 'b' * 40}]:
            with self.subTest(active=active), self.assertRaises(ValueError):
                desktop.check(candidate, active, 'version: 0.1.11\n')

    def test_downgrade_and_missing_provenance_are_rejected(self):
        active = {'run_id': '100', 'source_commit': 'a' * 40}
        candidate = {**active, 'version': '0.1.10'}
        with self.assertRaises(ValueError):
            desktop.check(candidate, active, 'version: 0.1.11\n')
        with self.assertRaises(ValueError):
            desktop.check({'version': '0.1.18'}, active, 'version: 0.1.11\n')


if __name__ == '__main__':
    unittest.main()
