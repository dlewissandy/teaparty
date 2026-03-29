#!/usr/bin/env python3
"""Tests for issue #269: teaparty.sh must verify uv is installed and install if missing.

Verifies:
 1. When uv is on PATH, the script proceeds directly to `uv run` with no install attempt.
 2. When uv is NOT on PATH, the script attempts to install it via curl.
 3. After a failed install (uv still missing), the script exits non-zero with a diagnostic.
 4. The check uses `command -v uv` (fast, POSIX) not `which`.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
TEAPARTY_SH = REPO_ROOT / "teaparty.sh"


class TestTeapartyShUvPreflightCheck(unittest.TestCase):
    """Specification tests for the uv pre-flight check in teaparty.sh."""

    def _read_script(self) -> str:
        return TEAPARTY_SH.read_text()

    # ── Structural checks ──────────────────────────────────────────────

    def test_script_checks_for_uv_before_calling_uv_run(self):
        """The uv availability check must appear before any `uv run` invocation."""
        source = self._read_script()
        check_pos = source.find("command -v uv")
        run_pos = source.find("uv run")
        self.assertNotEqual(check_pos, -1, "script must contain 'command -v uv'")
        self.assertNotEqual(run_pos, -1, "script must contain 'uv run'")
        self.assertLess(check_pos, run_pos,
                        "'command -v uv' must appear before 'uv run'")

    def test_script_contains_astral_install_command(self):
        """The script must use the Astral-recommended install method."""
        source = self._read_script()
        self.assertIn("https://astral.sh/uv/install.sh", source,
                      "script must reference the Astral uv install URL")

    def test_script_verifies_install_succeeded(self):
        """After attempting install, the script must re-check uv availability."""
        source = self._read_script()
        # There should be at least two checks for uv — one before install,
        # one after to verify.
        first = source.find("command -v uv")
        self.assertNotEqual(first, -1,
                            "script must contain 'command -v uv'")
        second = source.find("command -v uv", first + 1)
        self.assertNotEqual(second, -1,
                            "script must re-check uv after install attempt")

    # ── Behavioral checks via controlled execution ─────────────────────

    def test_exits_nonzero_when_uv_install_fails(self):
        """If uv is missing and install fails, script must exit non-zero with diagnostic."""
        # Create a wrapper script that stubs out curl and removes uv from PATH
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake curl that does nothing (simulates failed install)
            fake_bin = Path(tmpdir) / "bin"
            fake_bin.mkdir()
            fake_curl = fake_bin / "curl"
            fake_curl.write_text("#!/bin/sh\nexit 0\n")
            fake_curl.chmod(0o755)

            # Run teaparty.sh with PATH containing only essentials + our fake bin
            # but NOT uv
            minimal_path = f"{fake_bin}:/usr/bin:/bin"
            env = {
                "PATH": minimal_path,
                "HOME": tmpdir,
                "TERM": "dumb",
            }
            result = subprocess.run(
                ["bash", str(TEAPARTY_SH)],
                capture_output=True, text=True, env=env,
                timeout=10,
            )
            self.assertNotEqual(result.returncode, 0,
                                "script must exit non-zero when uv install fails")
            # Should contain a deliberate diagnostic — not just bash's generic
            # "command not found". The script must print its own message.
            combined = result.stdout + result.stderr
            self.assertIn("uv", combined.lower(),
                          "diagnostic must mention uv")
            # Must NOT be just bash's default error — script should have its own message
            self.assertFalse(
                "command not found" in combined.lower() and "install" not in combined.lower(),
                f"script should print its own diagnostic, not rely on bash's 'command not found': {combined!r}"
            )

    def test_no_install_attempt_when_uv_is_present(self):
        """When uv is already on PATH, no install should be attempted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_bin = Path(tmpdir) / "bin"
            fake_bin.mkdir()

            # Create a fake uv that just prints version and exits
            fake_uv = fake_bin / "uv"
            fake_uv.write_text("#!/bin/sh\necho 'uv 0.0.0-fake'\nexit 0\n")
            fake_uv.chmod(0o755)

            # Create a sentinel curl that signals if it was called
            sentinel = Path(tmpdir) / "curl_was_called"
            fake_curl = fake_bin / "curl"
            fake_curl.write_text(
                f"#!/bin/sh\ntouch {sentinel}\nexit 0\n"
            )
            fake_curl.chmod(0o755)

            # Also need python3 on path — use the real one
            python_bin = Path(sys.executable).parent

            env = {
                "PATH": f"{fake_bin}:{python_bin}:/usr/bin:/bin",
                "HOME": tmpdir,
                "TERM": "dumb",
            }
            # The script will fail at `uv run python3 -m projects.POC.bridge`
            # because fake uv doesn't actually run anything — that's fine,
            # we just want to confirm curl was NOT called.
            subprocess.run(
                ["bash", str(TEAPARTY_SH)],
                capture_output=True, text=True, env=env,
                timeout=10,
            )
            self.assertFalse(
                sentinel.exists(),
                "curl should not be called when uv is already on PATH"
            )


if __name__ == "__main__":
    unittest.main()
