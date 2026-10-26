"""Fetch pinned upstream binaries and corresponding source for redistribution."""
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import tarfile
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'v2.3.5'
REPO = 'https://github.com/XIU2/CloudflareSpeedTest'


def fetch(url):
    curl = shutil.which('curl')
    if not curl:
        raise RuntimeError('curl is required to download release assets')
    with tempfile.TemporaryDirectory(prefix='cfst-download-') as tmp:
        destination = Path(tmp) / 'download'
        subprocess.run([curl, '-q', '-L', '--fail', '--retry', '2', '--connect-timeout', '10',
                        '--max-time', '60', '-sS', '-o', str(destination), url],
                       check=True, timeout=210)
        return destination.read_bytes()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unpack(data, zipped):
    # Read only named regular members, never extract arbitrary archive paths.
    if zipped:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return {Path(n).name: archive.read(n) for n in archive.namelist()
                    if Path(n).name in ('cfst', 'cfst.exe', 'ip.txt') and not n.endswith('/')}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        return {Path(m.name).name: archive.extractfile(m).read() for m in archive.getmembers()
                if m.isfile() and Path(m.name).name in ('cfst', 'cfst.exe', 'ip.txt')}


def main():
    release = json.loads(fetch('https://api.github.com/repos/XIU2/CloudflareSpeedTest/releases/tags/' + VERSION))
    assets = {a['name']: a for a in release['assets']}
    def download(target):
        os_name, arch = target.split('-')
        ext = 'tar.gz' if os_name == 'linux' else 'zip'
        name = f'cfst_{os_name}_{arch}.{ext}'
        asset = assets[name]
        data = fetch(asset['browser_download_url'])
        expected = asset.get('digest')
        if not expected or expected != 'sha256:' + sha(data):
            raise RuntimeError('Missing or mismatched upstream SHA256: ' + name)
        files = unpack(data, ext == 'zip')
        exe_name = 'cfst.exe' if os_name == 'windows' else 'cfst'
        dest = ROOT / 'bin' / target / exe_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(files[exe_name])
        dest.chmod(0o755)
        print('Verified ' + target, flush=True)
        return target, {'file': dest.relative_to(ROOT).as_posix(), 'sha256': sha(files[exe_name]),
                        'archive_url': asset['browser_download_url'], 'archive_sha256': sha(data)}, files['ip.txt']
    targets = [f'{os_name}-{arch}' for os_name in ('windows', 'darwin', 'linux') for arch in ('amd64', 'arm64')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(download, targets))
    third = ROOT / 'third_party'
    third.mkdir(exist_ok=True)
    source_url = 'https://codeload.github.com/XIU2/CloudflareSpeedTest/tar.gz/refs/tags/' + VERSION
    source = fetch(source_url)
    (third / f'CloudflareSpeedTest-{VERSION}-source.tar.gz').write_bytes(source)
    with tarfile.open(fileobj=io.BytesIO(source), mode='r:gz') as archive:
        member = next(m for m in archive.getmembers() if m.isfile() and m.name.endswith('/LICENSE'))
        license_text = archive.extractfile(member).read()
    (third / 'CloudflareSpeedTest-LICENSE').write_bytes(license_text)
    # New wrapper code is distributed under GPL-3.0-only as well.
    (ROOT / 'LICENSE').write_bytes(license_text)
    data_dir = ROOT / 'data'
    data_dir.mkdir(exist_ok=True)
    ip_data = results[0][2]
    if any(r[2] != ip_data for r in results):
        raise RuntimeError('Upstream IP lists differ across platforms')
    (data_dir / 'ip.txt').write_bytes(ip_data)
    manifest = {'version': VERSION, 'upstream': REPO,
                'source': {'file': f'third_party/CloudflareSpeedTest-{VERSION}-source.tar.gz',
                           'url': source_url, 'sha256': sha(source)},
                'ip_list_sha256': sha(ip_data),
                'platforms': {target: record for target, record, _ in results}}
    (third / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
