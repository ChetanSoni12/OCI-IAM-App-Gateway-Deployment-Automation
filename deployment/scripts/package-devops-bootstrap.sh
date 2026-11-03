#!/usr/bin/env bash
set -euo pipefail

deployment_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$deployment_root/dist"
bundle_name="oci-iam-appgateway-devops-bootstrap"
bundle_dir="$output_dir/$bundle_name"
package_path="$output_dir/$bundle_name.zip"

rm -rf "$bundle_dir"
rm -f "$package_path"
mkdir -p "$bundle_dir"

cp -R "$deployment_root/foundation-stack" "$bundle_dir/foundation-stack"
cp -R "$deployment_root/pipeline-source" "$bundle_dir/pipeline-source"
cp -R "$deployment_root/docs" "$bundle_dir/docs"
cp "$deployment_root/../release/docs/appgateway-image-publication-runbook.md" \
  "$bundle_dir/docs/appgateway-image-publication-runbook.md"
cp "$deployment_root/scripts/bootstrap-devops.sh" "$bundle_dir/bootstrap-devops.sh"
cp "$deployment_root/README.md" "$bundle_dir/README.md"

# Local provider caches and bytecode are machine-specific build by-products.
find "$bundle_dir" -type d \( -name .terraform -o -name __pycache__ \) -prune -exec rm -rf {} +
find "$bundle_dir" -type f -name '.terraform.lock.hcl' -delete

(
  cd "$output_dir"
  zip -rq "$package_path" "$bundle_name"
)

rm -rf "$bundle_dir"
echo "$package_path"
