import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('safe_extract', Path(__file__).with_name('safe-extract.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SafeArchiveTests(unittest.TestCase):
    def make_archive(self, root, name, kind=tarfile.REGTYPE):
        archive = root / 'release.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            if kind == tarfile.REGTYPE:
                entry.size = 3
                output.addfile(entry, io.BytesIO(b'app'))
            else:
                entry.linkname = '/etc/passwd'
                output.addfile(entry)
        return archive

    def test_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module.safe_extract(self.make_archive(root, 'app/main.py'), root / 'out')
            self.assertEqual((root / 'out/app/main.py').read_bytes(), b'app')

    def test_rejects_unsafe_names(self):
        for name in ['../outside', '/etc/passwd', 'app/../../outside', 'app/.env', '.env', 'data/certificates.db', 'app\\main.py']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaises(ValueError):
                    module.safe_extract(self.make_archive(root, name), root / 'out')
                self.assertFalse((root / 'out').exists())

    def test_rejects_links_and_devices(self):
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaises(ValueError):
                    module.safe_extract(self.make_archive(root, 'app/main.py', kind), root / 'out')


if __name__ == '__main__':
    unittest.main()
