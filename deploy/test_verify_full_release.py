import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('verify_full_release', Path(__file__).with_name('verify-full-release.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        installer = '证事 Setup 0.1.4.exe'
        payloads = {
            'app/main.py': b'backend', 'app/email_service.py': b'email', 'requirements.txt': b'fastapi',
            'frontend/dist/index.html': b'web', 'frontend/dist/download/index.html': b'download',
            'deploy/setup-full-update.sh': b'install', 'deploy/setup-email-reminders-update.sh': b'backend-install',
            'deploy/verify-full-release.py': b'verify', f'desktop-updates/{installer}': b'exe',
            f'desktop-updates/{installer}.blockmap': b'blockmap',
        }
        digest = base64.b64encode(hashlib.sha512(b'exe').digest()).decode()
        payloads['desktop-updates/latest.yml'] = f'version: 0.1.4\npath: {installer}\nsha512: {digest}\n    size: 3\n'.encode()
        self.manifest = {'version': '0.1.4', 'installer': installer, 'files': {}}
        for relative, content in payloads.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            self.manifest['files'][relative] = hashlib.sha256(content).hexdigest()
        self.save_manifest()

    def save_manifest(self):
        (self.root / 'release.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_complete_release(self):
        self.assertEqual(module.verify(self.root)['version'], '0.1.4')

    def test_tampered_web(self):
        (self.root / 'frontend/dist/index.html').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
            module.verify(self.root)

    def test_missing_desktop(self):
        self.manifest['files'].pop('desktop-updates/证事 Setup 0.1.4.exe')
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Incomplete release'):
            module.verify(self.root)

    def test_secrets_not_allowed(self):
        (self.root / '.env').write_bytes(b'not-a-real-secret')
        self.manifest['files']['.env'] = hashlib.sha256(b'not-a-real-secret').hexdigest()
        self.save_manifest()
        with self.assertRaises(ValueError):
            module.verify(self.root)

    def test_stale_desktop_manifest(self):
        relative = 'desktop-updates/latest.yml'
        content = (self.root / relative).read_bytes().replace(b'version: 0.1.4', b'version: 0.1.3')
        (self.root / relative).write_bytes(content)
        self.manifest['files'][relative] = hashlib.sha256(content).hexdigest()
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'stale or invalid'):
            module.verify(self.root)


if __name__ == '__main__':
    unittest.main()
