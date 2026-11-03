from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_release.py"
VALIDATE_SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_release.py"
SPEC = importlib.util.spec_from_file_location("prepare_release", SCRIPT)
assert SPEC and SPEC.loader
prepare_release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare_release
SPEC.loader.exec_module(prepare_release)


class PrepareReleaseTests(unittest.TestCase):
    def test_find_package_uses_relative_download_url(self) -> None:
        package = prepare_release.find_package(
            [{"fileName": "idcs-appgateway-docker-26.1.06.zip", "downloadURL": "/downloads/image.zip"}],
            "idcs-appgateway-docker",
            "https://idcs-example.identity.oraclecloud.com",
        )
        self.assertEqual(package["download_url"], "https://idcs-example.identity.oraclecloud.com/downloads/image.zip")

    def test_version_is_extracted_from_package_name(self) -> None:
        self.assertEqual(
            prepare_release.version_from_file_name("idcs-appgateway-docker-26.1.06-2602110936.zip"),
            "26.1.06-2602110936",
        )

    def test_extract_zip_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "not allowed")
            with self.assertRaises(prepare_release.ReleaseError):
                prepare_release.extract_zip(archive_path, root / "extract")

    def test_selects_x86_64_compressed_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            x86_archive = root / "x86_64" / "appgateway.tar.gz"
            arm_archive = root / "arm64" / "appgateway.tar.gz"
            x86_archive.parent.mkdir()
            arm_archive.parent.mkdir()
            x86_archive.touch()
            arm_archive.touch()
            self.assertEqual(prepare_release.find_image_archive(root), x86_archive)

    def test_configured_missing_ca_bundle_is_rejected(self) -> None:
        with patch.dict("os.environ", {"SSL_CERT_FILE": "/does/not/exist"}, clear=False):
            with self.assertRaises(prepare_release.ReleaseError):
                prepare_release.trusted_tls_context()

    def test_release_manifest_validator_rejects_unsupported_architecture(self) -> None:
        manifest = {
            "schema_version": 1,
            "status": "candidate",
            "source_identity_domain_url": "https://idcs.example.com",
            "docker_package": {"file_name": "docker.zip"},
            "wallet_tool_package": {"file_name": "wallet.zip"},
            "version": "26.1.06",
            "prepared_local_image": "image:test",
            "architecture": "arm64",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATE_SCRIPT), str(path)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not x86_64-compatible", result.stderr)

    def test_release_manifest_validator_accepts_candidate_amd64_image(self) -> None:
        manifest = {
            "schema_version": 1,
            "status": "candidate",
            "source_identity_domain_url": "https://idcs.example.com",
            "docker_package": {"file_name": "docker.zip"},
            "wallet_tool_package": {"file_name": "wallet.zip"},
            "version": "26.1.06",
            "prepared_local_image": "image:test",
            "architecture": "amd64",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATE_SCRIPT), str(path)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Manifest validated", result.stdout)


if __name__ == "__main__":
    unittest.main()
