"""GPL-3.0-only. Verify one candidate with curl; do not run CFST."""
import argparse
import ipaddress
import shutil
import sys

from select_ip import domain_value, probe, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Repeat HTTPS curl checks for a domain, port and candidate IPv4. No CFST scan or configuration changes.")
    parser.add_argument('--domain', required=True, type=domain_value)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--ip', required=True)
    parser.add_argument('--attempts', type=int, default=5)
    parser.add_argument('--connect-timeout', type=int, default=5)
    parser.add_argument('--timeout', type=int, default=10)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1..65535')
    if not 1 <= args.attempts <= 20:
        parser.error('attempts must be 1..20')
    if not 1 <= args.connect_timeout <= args.timeout <= 60:
        parser.error('require 1 <= connect-timeout <= timeout <= 60')
    try:
        candidate = ipaddress.IPv4Address(args.ip)
    except ValueError:
        parser.error('ip must be an IPv4 address')
    if not candidate.is_global:
        parser.error('ip must be a public IPv4 address')
    curl = shutil.which('curl.exe' if sys.platform == 'win32' else 'curl')
    if not curl:
        parser.error('curl is required')
    print(f'Target: {args.domain}:{args.port}; candidate: {candidate}', flush=True)
    print('Direct network required: --noproxy does not bypass TUN/VPN.', flush=True)
    checks = []
    for index in range(1, args.attempts + 1):
        result = probe(curl, args.domain, args.port, str(candidate), args.connect_timeout, args.timeout)
        checks.append(result)
        print(f"{index}/{args.attempts} {'PASS' if result['ok'] else 'FAIL'} HTTP={result.get('http', '-')} total={result['seconds']}s colo={result['colo'] or '-'} {result['reason']}", flush=True)
    result = summary({'ip': str(candidate)}, checks)
    print(f"Success: {result['successes']}/{result['attempts']}; median successful response: {result['median_seconds']}s")
    print('Checks HTTPS edge connectivity only; not origin, WS/VLESS, bandwidth or future stability.')
    return 0 if result['successes'] == args.attempts else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Cancelled.', file=sys.stderr)
        sys.exit(130)
    except OSError as exc:
        print(f'Execution error: {exc}', file=sys.stderr)
        sys.exit(1)
