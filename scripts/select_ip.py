"""GPL-3.0-only. CFST TCP screening + bounded, domain-aware curl verification."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def domain_value(value):
    try:
        value = value.strip().rstrip('.').encode('idna').decode('ascii').lower()
    except UnicodeError as exc:
        raise argparse.ArgumentTypeError('Invalid domain') from exc
    labels = value.split('.')
    if len(value) > 253 or len(labels) < 2 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in labels):
        raise argparse.ArgumentTypeError('Enter a domain only, without scheme, port or path')
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise argparse.ArgumentTypeError('A domain is required, not an IP')


def platform_key(system=None, machine=None):
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine)
    if system not in ('windows', 'darwin', 'linux') or not arch:
        raise RuntimeError(f'Unsupported platform: {system}/{machine}; bundled: Windows/macOS/Linux x64/ARM64')
    return f'{system}-{arch}'


def bundled_binary():
    manifest = json.loads((ROOT / 'third_party' / 'manifest.json').read_text(encoding='utf-8'))
    record = manifest['platforms'][platform_key()]
    binary = ROOT / record['file']
    if hashlib.sha256(binary.read_bytes()).hexdigest() != record['sha256']:
        raise RuntimeError('Bundled CFST integrity check failed')
    if os.name != 'nt' and not os.access(binary, os.X_OK):
        binary.chmod(binary.stat().st_mode | 0o100)
    return binary


def candidates_from_csv(path, count):
    candidates = []
    seen = set()
    # CFST v2.3.5 uses Chinese headers; positional fields avoid locale dependency.
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.reader(stream):
            if len(row) < 5:
                continue
            try:
                ip = ipaddress.IPv4Address(row[0].strip())
                sent, received = int(row[1]), int(row[2])
                loss, delay = float(row[3]), float(row[4])
                if not ip.is_global or str(ip) in seen or not (sent > 0 and 0 < received <= sent):
                    continue
                if not (math.isfinite(delay) and delay >= 0 and math.isfinite(loss) and 0 <= loss <= 1):
                    continue
            except (ValueError, IndexError):
                continue
            seen.add(str(ip))
            candidates.append({'ip': str(ip), 'tcp_ms': delay, 'tcp_failure_ratio': loss})
    candidates.sort(key=lambda x: (x['tcp_failure_ratio'], x['tcp_ms']))
    # Mix fastest and evenly spaced remaining candidates; low-latency restricted
    # ranges must not crowd all ordinary edge addresses out of HTTPS verification.
    if len(candidates) <= count:
        return candidates
    first = max(1, count // 2)
    chosen = candidates[:first]
    rest = candidates[first:]
    n = count - first
    if n:
        chosen.extend(rest[round(i * (len(rest) - 1) / max(1, n - 1))] for i in range(n))
    return chosen


def probe(curl, domain, port, ip, connect_timeout, timeout):
    # Body goes to a temp file so trace's public client IP is never persisted.
    with tempfile.TemporaryDirectory(prefix='cfst-probe-') as temp:
        body_file = Path(temp) / 'body.txt'
        cmd = [curl, '-q', '-4', '--noproxy', '*', '--proto', '=https',
               '--resolve', f'{domain}:{port}:{ip}', '--connect-timeout', str(connect_timeout),
               '--max-time', str(timeout), '-sS', '-o', str(body_file),
               '-w', '%{http_code}|%{remote_ip}|%{time_total}',
               f'https://{domain}:{port}/cdn-cgi/trace']
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout + 3)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'reason': 'process_timeout', 'seconds': None, 'colo': ''}
        body = body_file.read_text(encoding='utf-8', errors='replace') if body_file.exists() else ''
        fields = dict(line.split('=', 1) for line in body.splitlines() if '=' in line)
        parts = proc.stdout.strip().split('|')
        code, remote = (parts + ['', ''])[:2]
        try:
            seconds = float(parts[2])
            if not math.isfinite(seconds) or seconds < 0:
                seconds = None
        except (ValueError, IndexError):
            seconds = None
        colo = fields.get('colo', '')
        valid_trace = fields.get('h', '').lower() == domain and bool(re.fullmatch('[A-Z0-9-]{2,16}', colo))
        ok = proc.returncode == 0 and code == '200' and remote == ip and valid_trace and seconds is not None
        reason = '' if ok else (f'curl_{proc.returncode}' if proc.returncode else f'http_{code}_or_invalid_trace')
        return {'ok': ok, 'reason': reason, 'http': code, 'seconds': seconds, 'colo': colo if valid_trace else ''}


def summary(candidate, attempts):
    passed = [a for a in attempts if a['ok']]
    return {**candidate, 'successes': len(passed), 'attempts': len(attempts),
            'median_seconds': statistics.median(a['seconds'] for a in passed) if passed else None,
            'colos': sorted(set(a['colo'] for a in passed)), 'checks': attempts}


def parser():
    p = argparse.ArgumentParser(description='Bundled CFST + HTTPS verification. No hosts/client changes.')
    p.add_argument('--domain', type=domain_value, help='Required target domain (no default)')
    p.add_argument('--port', type=int, help='Required HTTPS port (no default)')
    p.add_argument('--output', type=Path, help='New results directory; must not already exist')
    p.add_argument('--input-csv', type=Path, help='Reuse an existing CFST CSV, skip TCP screening')
    p.add_argument('--ip-file', type=Path, help='Override bundled IPv4 ranges')
    p.add_argument('--candidates', type=int, default=12)
    p.add_argument('--attempts', type=int, default=5)
    p.add_argument('--threads', type=int, default=50)
    p.add_argument('--tcp-attempts', type=int, default=4)
    p.add_argument('--max-loss', type=float, default=0)
    p.add_argument('--connect-timeout', type=int, default=5)
    p.add_argument('--timeout', type=int, default=10)
    p.add_argument('--screen-timeout', type=int, default=600)
    p.add_argument('--check', action='store_true', help='Check dependencies/integrity only; no scan')
    return p


def main(argv=None):
    p = parser()
    a = p.parse_args(argv)
    curl = shutil.which('curl.exe' if os.name == 'nt' else 'curl')
    if not curl:
        p.error('curl is required; install it using your OS package manager')
    binary = bundled_binary()
    if a.check:
        print(f'Platform: {platform_key()}\nCFST: {binary}\ncurl: {curl}')
        subprocess.run([str(binary), '-h'], check=True, stdout=subprocess.DEVNULL, timeout=15)
        return 0
    if a.domain is None:
        if not sys.stdin.isatty():
            p.error('--domain is required in non-interactive mode')
        try:
            a.domain = domain_value(input('Target domain (no default): '))
        except argparse.ArgumentTypeError as exc:
            p.error(str(exc))
    if a.port is None:
        if not sys.stdin.isatty():
            p.error('--port is required in non-interactive mode')
        try:
            a.port = int(input('HTTPS port (no default): '))
        except ValueError:
            p.error('Port must be an integer')
    ranges = [('port', 1, 65535), ('candidates', 1, 100), ('attempts', 2, 20), ('threads', 1, 200),
              ('tcp_attempts', 1, 20), ('connect_timeout', 1, 30), ('timeout', 1, 60), ('screen_timeout', 1, 3600)]
    for name, low, high in ranges:
        if not low <= getattr(a, name) <= high:
            p.error(f'{name} must be between {low} and {high}')
    if not 0 <= a.max_loss <= 1 or a.timeout < a.connect_timeout:
        p.error('max-loss must be 0..1; timeout must be >= connect-timeout')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    base = Path.cwd().resolve()
    if base == ROOT or ROOT in base.parents:
        base = Path.home()
    out = (a.output or base / f'cfst-results-{stamp}').resolve()
    if ROOT == out or ROOT in out.parents:
        p.error('Write results outside the skill directory to keep the shared package clean')
    out.mkdir(parents=True, exist_ok=False)
    csv_file = out / 'tcp.csv'
    started = datetime.now(timezone.utc).isoformat()
    print(f'Target: {a.domain}:{a.port}\nResults: {out}', flush=True)
    print('Direct network required: curl proxy bypass does not bypass TUN/VPN.', flush=True)
    if a.input_csv:
        shutil.copyfile(a.input_csv, csv_file)
    else:
        ip_file = (a.ip_file or ROOT / 'data' / 'ip.txt').resolve()
        if not ip_file.is_file():
            raise RuntimeError('IP input file does not exist')
        cmd = [str(binary), '-f', str(ip_file), '-tp', str(a.port), '-n', str(a.threads),
               '-t', str(a.tcp_attempts), '-dd', '-tlr', str(a.max_loss), '-p', '0', '-o', str(csv_file)]
        print('Step 1: TCP screening; progress is saved in cfst.log...', flush=True)
        with (out / 'cfst.log').open('wb') as log:
            subprocess.run(cmd, cwd=out, stdout=log, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=a.screen_timeout, check=True)
    candidates = candidates_from_csv(csv_file, a.candidates) if csv_file.exists() else []
    results = []
    for i, candidate in enumerate(candidates, 1):
        print(f'Step 2: {i}/{len(candidates)} {candidate["ip"]} ({a.attempts} checks)', flush=True)
        attempts = [probe(curl, a.domain, a.port, candidate['ip'], a.connect_timeout, a.timeout)
                    for _ in range(a.attempts)]
        results.append(summary(candidate, attempts))
        (out / 'progress.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    results.sort(key=lambda x: (-x['successes'] / x['attempts'],
                               x['median_seconds'] if x['median_seconds'] is not None else float('inf')))
    recommended = [r['ip'] for r in results if r['successes'] == r['attempts']]
    report = {'domain': a.domain, 'port': a.port, 'started_utc': started,
              'finished_utc': datetime.now(timezone.utc).isoformat(), 'cfst_version': 'v2.3.5',
              'recommended_candidates': recommended, 'results': results,
              'limitation': 'HTTPS edge connectivity only; not origin, WS/VLESS, sustained bandwidth or future stability.'}
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    with (out / 'verified.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['ip', 'successes', 'attempts', 'median_seconds', 'colos', 'tcp_ms'])
        for r in results:
            writer.writerow([r['ip'], r['successes'], r['attempts'], r['median_seconds'], ','.join(r['colos']), r['tcp_ms']])
            print(f'{r["ip"]}: {r["successes"]}/{r["attempts"]}, median={r["median_seconds"]}s, colo={r["colos"]}')
    print('Verified candidates: ' + (', '.join(recommended) if recommended else 'NONE; existing configuration unchanged'))
    print('No hosts, DNS or proxy configuration was changed.')
    return 0 if recommended else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nCancelled; no configuration changes.', file=sys.stderr)
        sys.exit(130)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
