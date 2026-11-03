#!/usr/bin/env python3
"""Validate an App Gateway release manifest before it is marked approved."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REQUIRED_FIELDS = (
    "schema_version",
    "status",
    "source_identity_domain_url",
    "docker_package",
    "wallet_tool_package",
    "version",
    "prepared_local_image",
    "architecture",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an OCI IAM App Gateway release manifest.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args()

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Manifest cannot be read: {exc}", file=sys.stderr)
        return 1

    missing = [field for field in REQUIRED_FIELDS if not manifest.get(field)]
    if missing:
        print(f"Manifest is missing required values: {', '.join(missing)}", file=sys.stderr)
        return 1
    if manifest["architecture"] not in {"amd64", "x86_64"}:
        print("Manifest architecture is not x86_64-compatible.", file=sys.stderr)
        return 1
    if args.require_approved:
        if manifest["status"] != "approved":
            print("Manifest has not been approved.", file=sys.stderr)
            return 1
        digest = manifest.get("promotion", {}).get("immutable_digest", "")
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            print("Approved manifest has no immutable OCI image digest.", file=sys.stderr)
            return 1

    print(f"Manifest validated: {manifest['version']} ({manifest['architecture']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

