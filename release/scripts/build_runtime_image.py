#!/usr/bin/env python3
"""Build the approved App Gateway runtime image from a validated vendor image.

The wrapper downloads a short-lived wallet object at container startup, then
executes the vendor image's original startup command. It avoids passing wallet
content through Terraform configuration-file volumes or long-lived image tags.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path


class RuntimeBuildError(RuntimeError):
    pass


BOOTSTRAP = """#!/usr/bin/env sh
set -eu

: "${APPGATEWAY_WALLET_URL:?APPGATEWAY_WALLET_URL is required}"
wallet_path=/usr/local/nginx/conf/cwallet.sso
mkdir -p "$(dirname "$wallet_path")"
umask 077
curl --fail --silent --show-error --location --retry 6 --retry-delay 5 \\
  "$APPGATEWAY_WALLET_URL" -o "$wallet_path"
test -s "$wallet_path"
unset APPGATEWAY_WALLET_URL
exec "$@"
"""


def run(command: list[str], *, cwd: Path | None = None) -> None:
    try:
        subprocess.run(command, cwd=cwd, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeBuildError(f"Runtime image build failed: {' '.join(command[:2])}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--wallet-tool-zip", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--engine", choices=("podman", "docker"), default="podman")
    parser.add_argument("--work-dir", type=Path, default=Path(".release-runtime"))
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    startup = manifest.get("startup", {})
    entrypoint = startup.get("entrypoint", [])
    command = startup.get("command", [])
    source_image = manifest.get("prepared_local_image")
    if not isinstance(source_image, str) or not source_image:
        raise RuntimeBuildError("Release manifest has no prepared source image")
    if not isinstance(entrypoint, list) or not isinstance(command, list) or not (entrypoint or command):
        raise RuntimeBuildError("Release manifest has no valid startup configuration")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    tool_dir = args.work_dir / "wallet-tool"
    with zipfile.ZipFile(args.wallet_tool_zip) as archive:
        archive.extractall(tool_dir)
    if not list(tool_dir.rglob("cgwallettool")):
        raise RuntimeBuildError("Wallet tool package does not contain cgwallettool")
    (args.work_dir / "appgateway-bootstrap").write_text(BOOTSTRAP, encoding="utf-8")

    original = entrypoint + command
    dockerfile = "\n".join(
        [
            f"FROM {source_image}",
            "USER root",
            "RUN (command -v dnf >/dev/null && dnf -y install curl libaio libstdc++) || (command -v microdnf >/dev/null && microdnf -y install curl libaio libstdc++)",
            "COPY wallet-tool/ /opt/idcs-wallet-tool/",
            "COPY appgateway-bootstrap /usr/local/bin/appgateway-bootstrap",
            "RUN chmod 0755 /usr/local/bin/appgateway-bootstrap && find /opt/idcs-wallet-tool -name cgwallettool -type f -exec chmod 0755 {} \\;",
            f"ENTRYPOINT {json.dumps(['/usr/local/bin/appgateway-bootstrap', *original])}",
        ]
    )
    (args.work_dir / "Dockerfile").write_text(dockerfile + "\n", encoding="utf-8")
    run([args.engine, "build", "--tag", args.image, str(args.work_dir)])
    run([args.engine, "run", "--rm", "--entrypoint", "/bin/sh", args.image, "-c", "command -v curl && find /opt/idcs-wallet-tool -name cgwallettool -type f | grep -q ."])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeBuildError as exc:
        print(f"Runtime image build failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
