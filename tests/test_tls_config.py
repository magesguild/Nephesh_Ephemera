from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mcp_experiments.config import TlsConfigError, resolve_tls


def _make_cert_pair(directory: Path) -> tuple[Path, Path]:
    """Generate a throwaway self-signed pair with openssl.

    Test fixture only. Nephesh itself never generates certificates — trust must
    be explicit operator configuration. A key pair is deliberately not committed
    to the repository.
    """
    cert = directory / "cert.pem"
    key = directory / "key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key), "-out", str(cert),
            "-days", "1", "-nodes", "-subj", "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


class TlsConfigTests(unittest.TestCase):
    """resolve_tls() either returns a proven-loadable pair or raises.

    Every failure test below asserts a raise rather than a falsy return. That
    asymmetry is the safety property: because None is returned only when TLS is
    disabled, no caller can mistake a broken configuration for "TLS is off" and
    serve plaintext in response to a request for TLS.
    """

    def test_tls_is_off_by_default(self) -> None:
        self.assertIsNone(resolve_tls(False, "", ""))

    def test_stray_paths_are_ignored_when_disabled(self) -> None:
        self.assertIsNone(resolve_tls(False, "/nonexistent/cert.pem", "/nonexistent/key.pem"))

    def test_empty_certificate_path_refuses(self) -> None:
        with self.assertRaises(TlsConfigError):
            resolve_tls(True, "", "/some/key.pem")

    def test_empty_key_path_refuses(self) -> None:
        with self.assertRaises(TlsConfigError):
            resolve_tls(True, "/some/cert.pem", "")

    def test_nonexistent_certificate_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent.pem"
            with self.assertRaises(TlsConfigError):
                resolve_tls(True, str(missing), str(missing))

    def test_directory_instead_of_file_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(TlsConfigError):
                resolve_tls(True, directory, directory)

    @unittest.skipIf(os.geteuid() == 0, "root bypasses file permissions")
    def test_unreadable_key_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cert = root / "cert.pem"
            key = root / "key.pem"
            cert.write_text("not a real certificate\n")
            key.write_text("not a real key\n")
            key.chmod(0o000)
            try:
                with self.assertRaises(TlsConfigError):
                    resolve_tls(True, str(cert), str(key))
            finally:
                key.chmod(0o600)

    def test_malformed_pair_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cert = root / "cert.pem"
            key = root / "key.pem"
            cert.write_text("-----BEGIN CERTIFICATE-----\nnonsense\n-----END CERTIFICATE-----\n")
            key.write_text("-----BEGIN PRIVATE KEY-----\nnonsense\n-----END PRIVATE KEY-----\n")
            with self.assertRaises(TlsConfigError):
                resolve_tls(True, str(cert), str(key))

    @unittest.skipUnless(shutil.which("openssl"), "openssl not available")
    def test_valid_pair_returns_the_configured_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cert, key = _make_cert_pair(Path(directory))
            resolved = resolve_tls(True, str(cert), str(key))
            self.assertEqual(resolved, (str(cert), str(key)))

    @unittest.skipUnless(shutil.which("openssl"), "openssl not available")
    def test_mismatched_pair_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            cert, _ = _make_cert_pair(first)
            _, key = _make_cert_pair(second)
            with self.assertRaises(TlsConfigError):
                resolve_tls(True, str(cert), str(key))


if __name__ == "__main__":
    unittest.main()
