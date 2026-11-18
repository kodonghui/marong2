"""Test the rollback candidate against a multi-host configuration."""

from pathlib import Path
import os
import shlex
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "deploy/pet/prepare-pet-withdrawal.py"
SAMPLE = ROOT / "deploy/pet/pet-ingress.example.yml"
HOST = "companion.example.invalid"
ACTIVE = (
    "# Global setting\n"
    "metrics: 127.0.0.1:5000\n"
    "ingress:\n"
    "  # The existing companion service\n"
    "  - hostname: existing.example.invalid\n"
    "    service: http://127.0.0.1:8010\n"
    "  - hostname: '*.example.invalid'\n"
    "    path: '^/shared$'\n"
    "    service: http://127.0.0.1:8011\n"
    + SAMPLE.read_text(encoding="utf-8").split("ingress:\n", 1)[1].replace("pet.example.invalid", HOST)
)
BLOCKED = (
    "# Global setting\n"
    "metrics: 127.0.0.1:5000\n"
    "ingress:\n"
    "  # The existing companion service\n"
    f"  - hostname: {HOST}\n"
    "    service: http_status:404\n"
    "  - hostname: existing.example.invalid\n"
    "    service: http://127.0.0.1:8010\n"
    "  - hostname: '*.example.invalid'\n"
    "    path: '^/shared$'\n"
    "    service: http://127.0.0.1:8011\n"
    "  - service: http_status:404\n"
)


def command(config, output, hostname=HOST):
    return subprocess.run([sys.executable, str(COMMAND), str(config), hostname, str(output)], capture_output=True)


def ingress(config, action, url=None):
    args = ["cloudflared", "tunnel", "--config", str(config), "ingress", action]
    if url is not None:
        args.append(url)
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


class Withdrawal(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.live = root / "active.yml"
        self.out = root / "candidate.yml"

    def test_disables_only_the_pet_hostname(self):
        self.live.write_bytes(ACTIVE.encode())
        result = command(self.live, self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.live.read_bytes(), ACTIVE.encode())
        self.assertEqual(self.out.read_bytes(), BLOCKED.encode())
        ingress(self.live, "validate")
        ingress(self.out, "validate")
        self.assertIn("service: http://127.0.0.1:8797", ingress(self.live, "rule", f"https://{HOST}/"))
        self.assertIn("service: http://127.0.0.1:8798", ingress(self.live, "rule", f"https://{HOST}/pet-call"))
        for path in ("/", "/pet-call", "/api/me", "/internal/calls/end", "/shared"):
            self.assertIn("service: http_status:404", ingress(self.out, "rule", f"https://{HOST}{path}"))
        for url, port in (("https://existing.example.invalid/", 8010),
                          ("https://another.example.invalid/shared", 8011)):
            for config in (self.live, self.out):
                self.assertIn(f"service: http://127.0.0.1:{port}", ingress(config, "rule", url))
        again = self.out.with_name("again.yml")
        self.assertEqual(command(self.out, again).returncode, 0)
        self.assertEqual(self.out.read_bytes(), again.read_bytes())

    def test_rejects_wrong_or_drifted_configuration(self):
        for config, host in ((ACTIVE, "existing.example.invalid"), (ACTIVE, "*.example.invalid"),
                             (ACTIVE.replace("8797", "8000"), HOST),
                             (ACTIVE.replace("ingress:\n", "ingress: []\ningress:\n"), HOST)):
            with self.subTest(config=config, host=host):
                self.live.write_bytes(config.encode())
                self.assertEqual(command(self.live, self.out, host).returncode, 1)
                self.assertEqual(self.live.read_bytes(), config.encode())
                self.assertFalse(self.out.exists())

    def test_never_overwrites_a_candidate_or_source(self):
        self.live.write_bytes(ACTIVE.encode())
        self.out.write_bytes(b"existing file")
        self.assertEqual(command(self.live, self.out).returncode, 1)
        self.assertEqual(self.out.read_bytes(), b"existing file")
        self.assertEqual(command(self.live, self.live).returncode, 1)
        self.assertEqual(self.live.read_bytes(), ACTIVE.encode())

    def test_rollback_runs_the_withdrawal_hook_even_if_stopping_fails(self):
        self.live.write_bytes(ACTIVE.encode())
        root = self.live.parent
        rollback = root / "rollback.sh"
        shutil.copyfile(COMMAND.with_name("rollback.sh"), rollback)
        hook = root / "remove-pet-hostname.sh"
        launcher = shlex.join([sys.executable, str(COMMAND), str(self.live), HOST, str(self.out)])
        hook.write_text(f"#!/usr/bin/env bash\nexec {launcher}\n", encoding="utf-8")
        hook.chmod(0o700)
        called = root / "systemctl-arguments"
        systemctl = root / "systemctl"
        systemctl.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$SYSTEMCTL_ARGUMENTS"\nexit 1\n',
                             encoding="utf-8")
        systemctl.chmod(0o700)
        env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"], "SYSTEMCTL_ARGUMENTS": str(called)}

        dry = subprocess.run(["bash", str(rollback), "--dry-run"], env=env, capture_output=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertFalse(self.out.exists())
        self.assertFalse(called.exists())
        applied = subprocess.run(["bash", str(rollback)], env=env, capture_output=True)
        self.assertEqual(applied.returncode, 1, applied.stderr)
        self.assertEqual(called.read_text(encoding="utf-8").splitlines(),
                         ["disable", "--now", "marong-pet-call.service", "marong-pet.service"])
        self.assertEqual(self.out.read_bytes(), BLOCKED.encode())
        self.assertEqual(self.live.read_bytes(), ACTIVE.encode())


if __name__ == "__main__":
    unittest.main(verbosity=2)
