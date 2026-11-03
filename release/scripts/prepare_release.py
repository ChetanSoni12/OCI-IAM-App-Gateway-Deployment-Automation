#!/usr/bin/env python3
"""Prepare an OCI IAM App Gateway Docker release for controlled promotion.

The script intentionally does not create OCI resources or push an image. OCI
DevOps owns promotion to private OCIR through an output artifact. This keeps
local validation useful without requiring an OCIR auth token.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


METADATA_PATH = "/admin/v1/LatestBinaryFileInfoVersionRetriever"
DOCKER_PACKAGE_FRAGMENT = "idcs-appgateway-docker"
WALLET_PACKAGE_FRAGMENT = "idcs-appgateway-wallet-tool"
SUPPORTED_ARCHITECTURES = {"amd64", "x86_64"}


class ReleaseError(RuntimeError):
    """A release package or image failed a pre-promotion check."""


def normalise_domain_url(value: str) -> str:
    return value.rstrip("/")


def trusted_tls_context() -> ssl.SSLContext:
    """Use an explicitly supplied trusted CA bundle when the runner needs one."""
    certificate_bundle = os.environ.get("SSL_CERT_FILE", "").strip()
    if certificate_bundle:
        bundle_path = Path(certificate_bundle)
        if not bundle_path.is_file():
            raise ReleaseError(f"Configured SSL_CERT_FILE does not exist: {bundle_path}")
        return ssl.create_default_context(cafile=str(bundle_path))
    return ssl.create_default_context()


def request_json(url: str, headers: dict[str, str], data: bytes | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60, context=trusted_tls_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ReleaseError(f"{request.get_method()} {url} failed: HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ReleaseError(f"Cannot reach {url}: {exc.reason}") from exc


def get_access_token(domain_url: str, client_id: str, client_secret: str) -> str:
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": "urn:opc:idm:__myscopes__"}).encode(
        "utf-8"
    )
    payload = request_json(
        f"{domain_url}/oauth2/v1/token",
        {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        body,
    )
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ReleaseError("IAM token response did not include an access_token")
    return token


def find_package(resources: list[dict[str, Any]], fragment: str, domain_url: str) -> dict[str, str]:
    for item in resources:
        file_name = item.get("fileName")
        download_url = item.get("downloadURL")
        if isinstance(file_name, str) and isinstance(download_url, str) and fragment in file_name:
            return {"file_name": file_name, "download_url": urllib.parse.urljoin(f"{domain_url}/", download_url)}
    raise ReleaseError(f"IAM metadata did not contain a package matching '{fragment}'")


def release_metadata(domain_url: str, token: str) -> tuple[dict[str, str], dict[str, str]]:
    payload = request_json(
        f"{domain_url}{METADATA_PATH}",
        {"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    resources = payload.get("Resources")
    if not isinstance(resources, list):
        raise ReleaseError("IAM package metadata response did not include Resources")
    typed_resources = [item for item in resources if isinstance(item, dict)]
    return (
        find_package(typed_resources, DOCKER_PACKAGE_FRAGMENT, domain_url),
        find_package(typed_resources, WALLET_PACKAGE_FRAGMENT, domain_url),
    )


def download_zip(url: str, destination: Path, token: str) -> None:
    temp_path = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/octet-stream"})
    try:
        with urllib.request.urlopen(request, timeout=120, context=trusted_tls_context()) as response, temp_path.open("wb") as output:
            shutil.copyfileobj(response, output)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ReleaseError(f"Download failed for {destination.name}: HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ReleaseError(f"Download failed for {destination.name}: {exc.reason}") from exc

    try:
        with zipfile.ZipFile(temp_path) as archive:
            invalid_member = archive.testzip()
            if invalid_member:
                raise ReleaseError(f"Downloaded ZIP is corrupt at member: {invalid_member}")
            if not archive.namelist():
                raise ReleaseError("Downloaded ZIP has no entries")
    except zipfile.BadZipFile as exc:
        raise ReleaseError(f"Downloaded file is not a valid ZIP: {destination.name}") from exc
    finally:
        if destination.exists():
            destination.unlink()

    temp_path.replace(destination)


def extract_zip(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            member_path = destination / member.filename
            try:
                member_path.resolve().relative_to(destination.resolve())
            except ValueError:
                raise ReleaseError(f"Unsafe ZIP member rejected: {member.filename}")
        archive.extractall(destination)


def find_image_archive(extracted_dir: Path) -> Path:
    """Select the x86_64 Docker archive from an App Gateway download.

    Oracle App Gateway packages have used .tar, .tar.gz, and .tgz archive
    formats, sometimes containing archives for multiple processor types.
    """
    candidates = sorted(
        path
        for path in extracted_dir.rglob("*")
        if path.is_file() and path.name.endswith((".tar", ".tar.gz", ".tgz"))
    )
    x86_candidates = [
        path
        for path in candidates
        if any(part.lower() in {"x86_64", "amd64", "linux_amd64"} for part in path.parts)
    ]
    if len(x86_candidates) == 1:
        return x86_candidates[0]
    if len(candidates) == 1:
        return candidates[0]

    names = ", ".join(str(path.relative_to(extracted_dir)) for path in candidates) or "none"
    if x86_candidates:
        raise ReleaseError(f"Expected one x86_64 Docker archive; found: {names}")
    raise ReleaseError(f"No x86_64 Docker archive found in App Gateway package. Available archives: {names}")


def run(command: list[str], sensitive: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except FileNotFoundError as exc:
        raise ReleaseError(f"Required container engine was not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = "container engine command failed" if sensitive else exc.stdout.strip()
        raise ReleaseError(f"{' '.join(command[:2])} failed: {detail}") from exc


def image_from_load_output(output: str) -> str:
    match = re.search(r"(?:Loaded image(?:\(s\))?|Loaded image):\s*(\S+)", output)
    if not match:
        raise ReleaseError(f"Could not identify the image loaded from the package: {output.strip()}")
    return match.group(1)


def prepare_image(engine: str, image_tar: Path, local_image: str) -> tuple[str, str, list[str], list[str]]:
    loaded = run([engine, "load", "--input", str(image_tar)])
    source_image = image_from_load_output(loaded.stdout)
    run([engine, "tag", source_image, local_image])
    architecture = run([engine, "image", "inspect", "--format", "{{.Architecture}}", local_image]).stdout.strip()
    if architecture not in SUPPORTED_ARCHITECTURES:
        raise ReleaseError(
            f"Image architecture '{architecture}' is not supported. The approved release must be amd64/x86_64."
        )
    config = run([engine, "image", "inspect", "--format", "{{json .Config}}", local_image])
    try:
        image_config = json.loads(config.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseError("Could not read the App Gateway image startup configuration") from exc
    entrypoint = image_config.get("Entrypoint") or []
    command = image_config.get("Cmd") or []
    if not all(isinstance(value, str) for value in entrypoint + command):
        raise ReleaseError("The App Gateway image startup configuration is invalid")
    if not entrypoint and not command:
        raise ReleaseError("The App Gateway image does not define a startup command")
    return source_image, architecture, entrypoint, command


def version_from_file_name(file_name: str) -> str:
    cleaned = file_name.removesuffix(".zip")
    match = re.search(r"(\d+(?:\.\d+)+(?:-\d+)?)$", cleaned)
    return match.group(1) if match else cleaned


def load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"Existing manifest is not valid JSON: {path}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a validated OCI IAM App Gateway Docker release.")
    parser.add_argument("--work-dir", type=Path, default=Path(".release-work"), help="Temporary release workspace.")
    parser.add_argument("--manifest", type=Path, default=Path("approved-release.json"), help="Candidate manifest to write.")
    parser.add_argument("--approved-manifest", type=Path, help="Existing approved manifest used for no-change detection.")
    parser.add_argument("--engine", default=os.environ.get("RELEASE_ENGINE", "docker"), choices=("docker", "podman"))
    parser.add_argument("--local-image", help="Local image tag to produce. Default derives from package version.")
    return parser.parse_args()


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ReleaseError(f"Missing required environment variable: {name}")
    return value


def main() -> int:
    args = parse_args()
    domain_url = normalise_domain_url(required_environment("RELEASE_IDENTITY_DOMAIN_URL"))
    client_id = required_environment("RELEASE_CLIENT_ID")
    client_secret = required_environment("RELEASE_CLIENT_SECRET")

    token = get_access_token(domain_url, client_id, client_secret)
    docker_package, wallet_package = release_metadata(domain_url, token)
    approved = load_manifest(args.approved_manifest) if args.approved_manifest else None

    if approved and approved.get("docker_package", {}).get("file_name") == docker_package["file_name"]:
        print(json.dumps({"status": "unchanged", "docker_package": docker_package["file_name"]}, indent=2))
        return 0

    args.work_dir.mkdir(parents=True, exist_ok=True)
    docker_zip = args.work_dir / docker_package["file_name"]
    wallet_zip = args.work_dir / wallet_package["file_name"]
    download_zip(docker_package["download_url"], docker_zip, token)
    download_zip(wallet_package["download_url"], wallet_zip, token)

    with tempfile.TemporaryDirectory(prefix="appgateway-release-") as temporary_directory:
        extracted_dir = Path(temporary_directory)
        extract_zip(docker_zip, extracted_dir)
        image_tar = find_image_archive(extracted_dir)
        version = version_from_file_name(docker_package["file_name"])
        local_image = args.local_image or f"appgateway-release:{version}"
        source_image, architecture, entrypoint, command = prepare_image(args.engine, image_tar, local_image)

    manifest = {
        "schema_version": 1,
        "status": "candidate",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_identity_domain_url": domain_url,
        # Download URLs are transient implementation details and are deliberately
        # not retained in a release manifest.
        "docker_package": {"file_name": docker_package["file_name"]},
        "wallet_tool_package": {"file_name": wallet_package["file_name"]},
        "version": version,
        "source_image": source_image,
        "prepared_local_image": local_image,
        "architecture": architecture,
        "startup": {"entrypoint": entrypoint, "command": command},
        "promotion": {
            "approved_ocir_image": "Set by OCI DevOps deliver-artifact stage.",
            "immutable_digest": "Set after private OCIR promotion.",
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReleaseError as exc:
        print(f"Release preparation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
