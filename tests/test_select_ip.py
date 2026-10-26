import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('select_ip', Path(__file__).resolve().parents[1] / 'scripts' / 'select_ip.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class SelectionTests(unittest.TestCase):
    def test_domain_no_shell_or_url_input(self):
        self.assertEqual(app.domain_value('EXAMPLE.COM.'), 'example.com')
        for value in ('', 'https://example.com', 'example.com:443', 'example.com/x', 'example.com;echo hi', '127.0.0.1'):
            with self.assertRaises(app.argparse.ArgumentTypeError):
                app.domain_value(value)

    def test_platforms(self):
        for system, arch, expected in [('Windows', 'AMD64', 'windows-amd64'), ('Windows', 'ARM64', 'windows-arm64'),
                                       ('Darwin', 'arm64', 'darwin-arm64'), ('Darwin', 'x86_64', 'darwin-amd64'),
                                       ('Linux', 'aarch64', 'linux-arm64'), ('Linux', 'x86_64', 'linux-amd64')]:
            self.assertEqual(app.platform_key(system, arch), expected)
        with self.assertRaises(RuntimeError):
            app.platform_key('Linux', 'mips')

    def test_csv_filters_private_invalid_and_duplicates_and_samples_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.csv'
            path.write_text('IP,Sent,Received,Loss,Delay\n127.0.0.1,4,4,0,1\n10.1.1.1,4,4,0,1\n'
                            '104.16.1.1,4,4,0,1\n104.16.1.1,4,4,0,1\nbad,4,4,0,1\n'
                            '104.16.1.2,4,4,0,NaN\n' +
                            ''.join(f'104.17.1.{i},4,4,0,{i + 2}\n' for i in range(1, 21)), encoding='utf-8-sig')
            rows = app.candidates_from_csv(path, 6)
            self.assertEqual(len(rows), 6)
            self.assertEqual(rows[0]['ip'], '104.16.1.1')
            self.assertIn('104.17.1.20', [r['ip'] for r in rows])

    def fake_curl(self, code='200', host='example.com', exit_code=0, body=None):
        def run(cmd, **kwargs):
            self.assertIn('--noproxy', cmd)
            self.assertNotIn('-k', cmd)
            self.assertEqual(cmd[1], '-q')
            ip = cmd[cmd.index('--resolve') + 1].split(':')[-1]
            Path(cmd[cmd.index('-o') + 1]).write_text(body if body is not None else f'h={host}\ncolo=LAX\nip=203.0.113.9\n')
            return subprocess.CompletedProcess(cmd, exit_code, f'{code}|{ip}|0.5', '')
        return run

    def test_probe_preserves_domain_and_does_not_record_public_client_ip(self):
        with patch.object(app.subprocess, 'run', side_effect=self.fake_curl()) as run:
            result = app.probe('curl', 'example.com', 8443, '104.16.1.1', 2, 4)
        self.assertTrue(result['ok'])
        self.assertEqual(run.call_args.args[0][-1], 'https://example.com:8443/cdn-cgi/trace')
        self.assertNotIn('203.0.113.9', json.dumps(result))

    def test_probe_rejects_1034_wrong_host_and_timeout(self):
        cases = [self.fake_curl(code='403', body='error code: 1034'), self.fake_curl(host='wrong.example'), self.fake_curl(exit_code=28)]
        for fake in cases:
            with patch.object(app.subprocess, 'run', side_effect=fake):
                self.assertFalse(app.probe('curl', 'example.com', 443, '104.16.1.1', 2, 4)['ok'])
        with patch.object(app.subprocess, 'run', side_effect=subprocess.TimeoutExpired('curl', 7)):
            self.assertFalse(app.probe('curl', 'example.com', 443, '104.16.1.1', 2, 4)['ok'])

    def test_missing_target_stops_before_scanning(self):
        with patch.object(app, 'bundled_binary', return_value=Path('cfst')), patch.object(app.shutil, 'which', return_value='curl'), \
             patch.object(app.sys.stdin, 'isatty', return_value=False), patch.object(app.subprocess, 'run') as run, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                app.main([])
            run.assert_not_called()

    def test_end_to_end_both_steps_report_and_no_live_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'result'
            ip_file = Path(tmp) / 'ip.txt'
            ip_file.write_text('104.16.1.1\n104.16.1.2\n')
            def fake_run(cmd, **kwargs):
                if '-tp' in cmd:
                    self.assertEqual(cmd[cmd.index('-tp') + 1], '8443')
                    self.assertIn('-dd', cmd)
                    Path(cmd[cmd.index('-o') + 1]).write_text('IP,Sent,Received,Loss,Delay\n104.16.1.1,4,4,0,10\n104.16.1.2,4,4,0,20\n')
                    return subprocess.CompletedProcess(cmd, 0)
                resolve = cmd[cmd.index('--resolve') + 1]
                return self.fake_curl(code='403' if resolve.endswith('.1') else '200')(cmd, **kwargs)
            with patch.object(app, 'bundled_binary', return_value=Path('cfst')), patch.object(app.shutil, 'which', return_value='curl'), \
                 patch.object(app.subprocess, 'run', side_effect=fake_run), contextlib.redirect_stdout(io.StringIO()):
                status = app.main(['--domain', 'example.com', '--port', '8443', '--output', str(out), '--attempts', '2', '--ip-file', str(ip_file)])
            self.assertEqual(status, 0)
            report = json.loads((out / 'report.json').read_text())
            self.assertEqual(report['recommended_candidates'], ['104.16.1.2'])
            self.assertEqual(report['results'][0]['successes'], 2)
            self.assertNotIn('203.0.113.9', (out / 'report.json').read_text())
            self.assertTrue((out / 'verified.csv').exists())

    def test_failed_candidates_never_recommended(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.csv'
            source.write_text('IP,Sent,Received,Loss,Delay\n104.16.1.1,4,4,0,10\n')
            out = Path(tmp) / 'output'
            with patch.object(app, 'bundled_binary', return_value=Path('cfst')), patch.object(app.shutil, 'which', return_value='curl'), \
                 patch.object(app.subprocess, 'run', side_effect=self.fake_curl(code='403')), contextlib.redirect_stdout(io.StringIO()):
                status = app.main(['--domain', 'example.com', '--port', '443', '--input-csv', str(source), '--output', str(out), '--attempts', '2'])
            self.assertEqual(status, 2)
            self.assertEqual(json.loads((out / 'report.json').read_text())['recommended_candidates'], [])


if __name__ == '__main__':
    unittest.main()
