"""Regression checks for legacy scheduler isolation and slot import selection."""
import asyncio
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_slot', ROOT / 'deploy/ci/prepare-slot.py')
prepare_slot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_slot)

LEGACY = '''import os
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(_):
    scheduler.add_job(scheduled_due_date_check, "cron", hour=8)
    scheduler.add_job(scheduled_check, "cron", hour=9)
    # A legacy catchup must also be disabled in API instances.
    await scheduled_due_date_check()
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)
'''


class SchedulerIsolationTests(unittest.TestCase):
    def exercise(self, enabled):
        events = []

        class Scheduler:
            running = False

            def add_job(self, *args, **kwargs): events.append('job')
            def start(self):
                self.running = True
                events.append('start')
            def shutdown(self, **kwargs):
                self.running = False
                events.append('shutdown')

        async def catchup(): events.append('catchup')
        namespace = {'scheduler': Scheduler(), 'scheduled_due_date_check': catchup,
                     'scheduled_check': catchup}
        transformed = prepare_slot.guard_legacy_scheduler(LEGACY)
        exec(transformed, namespace)

        async def run():
            async with namespace['lifespan'](None):
                events.append('serve')

        with patch.dict(os.environ, {'SCHEDULER_ENABLED': enabled}):
            asyncio.run(run())
        return events

    def test_legacy_api_has_no_jobs_or_startup_catchup(self):
        self.assertEqual(self.exercise('false'), ['serve'])

    def test_legacy_scheduler_still_sends_and_shuts_down(self):
        self.assertEqual(self.exercise('true'), ['job', 'job', 'catchup', 'start', 'serve', 'shutdown'])

    def test_prepare_is_idempotent(self):
        once = prepare_slot.guard_legacy_scheduler(LEGACY)
        self.assertEqual(prepare_slot.guard_legacy_scheduler(once), once)

    def test_native_guard_is_unchanged(self):
        source = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        self.assertEqual(prepare_slot.guard_legacy_scheduler(source), source)

    def test_unrecognised_startup_fails_closed(self):
        unknown = LEGACY.replace('    scheduler.start()', '    unrelated_startup()\n    scheduler.start()')
        with self.assertRaises(ValueError):
            prepare_slot.guard_legacy_scheduler(unknown)


class SlotImportTests(unittest.TestCase):
    def test_explicit_app_dir_beats_old_app_in_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / 'app'
            new = root / 'release/app'
            for folder, marker in [(old, 'old-working-directory'), (new, 'candidate-release')]:
                folder.mkdir(parents=True)
                (folder / '__init__.py').write_text('')
                (folder / 'main.py').write_text(
                    'async def app(scope, receive, send):\n'
                    '    await send({"type": "http.response.start", "status": 200, "headers": []})\n'
                    f'    await send({{"type": "http.response.body", "body": b"{marker}"}})\n'
                )
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            process = subprocess.Popen(
                [sys.executable, '-m', 'uvicorn', 'app.main:app', '--app-dir', str(root / 'release'),
                 '--host', '127.0.0.1', '--port', str(port), '--lifespan', 'off'],
                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                response = None
                for _ in range(50):
                    if process.poll() is not None:
                        self.fail(process.stderr.read().decode(errors='replace'))
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/', timeout=0.2) as result:
                            response = result.read()
                        break
                    except OSError:
                        time.sleep(0.1)
                self.assertEqual(response, b'candidate-release')
            finally:
                process.terminate()
                process.communicate(timeout=10)


if __name__ == '__main__':
    unittest.main()
