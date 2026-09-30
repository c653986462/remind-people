import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch, Mock
import zipfile

spec = importlib.util.spec_from_file_location('artifact_pull', Path(__file__).with_name('pull-artifact.py'))
pull = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pull)
NAME = 'certificate-manager-full-0.1.18.tar.gz'
DATA = b'verified archive bytes'
DIGEST = hashlib.sha256(DATA).hexdigest()


class ArtifactPullTests(unittest.TestCase):
    def make_zip(self, root, invalid=None):
        path = root / 'input.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            if invalid == 'symlink':
                member = zipfile.ZipInfo(NAME)
                member.create_system = 3
                member.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(member, DATA)
            else:
                archive.writestr(NAME, DATA)
            archive.writestr(NAME + '.sha256', DIGEST + '  ' + NAME)
            if invalid == 'traversal':
                archive.writestr('../outside', b'bad')
        return path

    def test_safe_zip_and_two_layers_of_hash_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            zip_path = self.make_zip(root)
            self.assertEqual(pull.unpack(zip_path, root, NAME, DIGEST).read_bytes(), DATA)
            with self.assertRaises(ValueError):
                pull.unpack(zip_path, root, NAME, '0' * 64)

    def test_rejects_zip_paths_and_links(self):
        for invalid in ('traversal', 'symlink'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaises(ValueError):
                    pull.unpack(self.make_zip(root, invalid), root, NAME, DIGEST)
                self.assertFalse((root / 'verified.tar.gz').exists())

    def test_signed_url_is_https_storage_only(self):
        pull.valid_storage_url('https://production.blob.core.windows.net/artifact?signed=abc')
        for url in ('http://production.blob.core.windows.net/x', 'https://example.com/x',
                    'https://production.blob.core.windows.net.evil.example/x',
                    'https://user:password@production.blob.core.windows.net/x',
                    'https://production.blob.core.windows.net:444/x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                pull.valid_storage_url(url)

    def test_parallel_ranges_and_zip_digest(self):
        raw = b'artifact zip data' * 100
        class Response(io.BytesIO):
            status = 206
        def open_range(request, timeout):
            left, right = map(int, request.get_header('Range').removeprefix('bytes=').split('-'))
            response = Response(raw[left:right + 1])
            response.headers = {'Content-Range': f'bytes {left}-{right}/{len(raw)}'}
            return response
        opener = Mock()
        opener.open.side_effect = open_range
        payload = dict(size=len(raw), url='https://production.blob.core.windows.net/x',
                       zip_digest=hashlib.sha256(raw).hexdigest())
        with tempfile.TemporaryDirectory() as directory, patch.object(pull.urllib.request, 'build_opener', return_value=opener):
            result = pull.download(payload, Path(directory))
            self.assertEqual(result.read_bytes(), raw)
            self.assertEqual(opener.open.call_count, 16)

    def test_range_ignored_cannot_publish(self):
        response = io.BytesIO(b'data')
        response.status = 200
        response.headers = {}
        opener = Mock()
        opener.open.return_value = response
        payload = dict(size=100, url='https://production.blob.core.windows.net/x', zip_digest='0' * 64)
        with tempfile.TemporaryDirectory() as directory, patch.object(pull.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(ValueError):
                pull.download(payload, Path(directory))
            self.assertFalse((Path(directory) / 'artifact.zip').exists())

    def test_partial_ranges_resume_without_redownloading_prefix(self):
        raw = b'zip bytes for resume' * 100
        requested = []
        class Response(io.BytesIO):
            status = 206
        def open_range(request, timeout):
            left, right = map(int, request.get_header('Range').removeprefix('bytes=').split('-'))
            requested.append((left, right))
            response = Response(raw[left:right + 1])
            response.headers = {'Content-Range': f'bytes {left}-{right}/{len(raw)}'}
            return response
        opener = Mock()
        opener.open.side_effect = open_range
        payload = dict(size=len(raw), url='https://production.blob.core.windows.net/x',
                       zip_digest=hashlib.sha256(raw).hexdigest())
        with tempfile.TemporaryDirectory() as directory, patch.object(pull.urllib.request, 'build_opener', return_value=opener):
            stage = Path(directory)
            for index in range(16):
                left, right = len(raw) * index // 16, len(raw) * (index + 1) // 16
                end = right if index == 0 else left + 10
                (stage / str(index)).write_bytes(raw[left:end])
            self.assertEqual(pull.download(payload, stage).read_bytes(), raw)
            self.assertEqual(len(requested), 15)
            self.assertTrue(all(left % 125 == 10 for left, _ in requested))

    def test_remote_unprivileged_atomic_publish_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            zip_path = self.make_zip(root)
            target = root / 'release-100-2.tar.gz'
            target.write_bytes(b'partial prior transfer')
            payload = dict(target=str(target), archive=NAME, archive_digest=DIGEST,
                           zip_digest='0' * 64, size=100)
            with patch.object(pull, 'INCOMING', root), patch.object(pull.os, 'getuid', create=True, return_value=1000), patch.object(pull, 'download', return_value=zip_path):
                pull.remote(payload)
                self.assertEqual(target.read_bytes(), DATA)
                self.assertFalse(list(root.glob('artifact-pull-*')))
                payload['archive_digest'] = '1' * 64
                with self.assertRaises(ValueError):
                    pull.remote(payload)
                self.assertEqual(target.read_bytes(), DATA)
                self.assertFalse(list(root.glob('artifact-pull-*')))

    def test_runner_does_not_send_token_in_stdin_args_or_child_env(self):
        environment = dict(GITHUB_REPOSITORY='owner/repo', GITHUB_RUN_ID='100', GH_ARTIFACT_TOKEN='private-test-token')
        listing = dict(artifacts=[dict(name='desktop-100', expired=False, digest='sha256:' + 'a' * 64, id=1, size_in_bytes=100)])
        with patch.dict(os.environ, environment), patch.object(pull, 'api_request', side_effect=[listing, 'https://production.blob.core.windows.net/x?signed=short']), patch.object(pull.subprocess, 'run', return_value=Mock(returncode=0)) as child:
            pull.runner([NAME, DIGEST, '/var/lib/certificate-manager-ci/incoming/release-100-2.tar.gz', 'ssh', 'host'])
            args, keywords = child.call_args
            self.assertNotIn('private-test-token', str(args))
            self.assertNotIn('private-test-token', keywords['input'])
            self.assertNotIn('GH_ARTIFACT_TOKEN', keywords['env'])
            self.assertEqual(json.loads(keywords['input'])['archive_digest'], DIGEST)

    def test_timeouts_preserve_cache_and_next_attempt_cleans_it_on_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            zip_path = self.make_zip(root)
            target = root / 'release-100-2.tar.gz'
            payload = dict(target=str(target), archive=NAME, archive_digest=DIGEST,
                           zip_digest='a' * 64, size=100)
            def interrupted(payload, stage):
                (stage / '0').write_bytes(b'partial')
                raise TimeoutError()
            with patch.object(pull, 'INCOMING', root), patch.object(pull.os, 'getuid', create=True, return_value=1000):
                with patch.object(pull, 'download', side_effect=interrupted), self.assertRaises(TimeoutError):
                    pull.remote(payload)
                self.assertEqual(len(list(root.glob('artifact-pull-*'))), 1)
                self.assertFalse(target.exists())
                with patch.object(pull, 'download', return_value=zip_path):
                    pull.remote(payload)
                self.assertEqual(target.read_bytes(), DATA)
                self.assertFalse(list(root.glob('artifact-pull-*')))


if __name__ == '__main__':
    unittest.main()
