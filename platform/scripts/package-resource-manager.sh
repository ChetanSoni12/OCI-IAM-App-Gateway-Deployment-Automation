#!/usr/bin/env bash
set -euo pipefail

platform_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$platform_root/dist"
package_path="$output_dir/oci-iam-appgateway-release-platform.zip"
staging_dir="$(mktemp -d)"
trap 'rm -rf "$staging_dir"' EXIT

mkdir -p "$output_dir"
rm -f "$package_path"
cp -R "$platform_root"/. "$staging_dir"/
rm -rf "$staging_dir/.terraform" "$staging_dir/dist"
cp "$platform_root/../release/docs/appgateway-image-publication-runbook.md" \
  "$staging_dir/docs/appgateway-image-publication-runbook.md"

(
  cd "$staging_dir"
  zip -rq "$package_path" . \
    -x "*.tfstate" \
    -x "*.tfstate.*" \
    -x "**/__pycache__/*" \
    -x "**/*.pyc" \
    -x ".DS_Store"
)

echo "$package_path"

