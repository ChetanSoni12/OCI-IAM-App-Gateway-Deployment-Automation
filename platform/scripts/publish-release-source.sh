#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: publish-release-source.sh \
  --repository-url <OCI DevOps Git URL> \
  --release-domain-url <https://identity-domain> \
  --release-client-id-secret-id <Vault secret OCID> \
  --release-client-secret-secret-id <Vault secret OCID>

Run from the project root in OCI Cloud Shell after the platform stack completes.
The script creates a temporary Git worktree, writes build_spec.yaml with Vault
secret OCIDs only, and creates or updates the release source in the private
DevOps repository.
EOF
}

repository_url=""
release_domain_url=""
release_client_id_secret_id=""
release_client_secret_secret_id=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repository-url) repository_url="$2"; shift 2 ;;
    --release-domain-url) release_domain_url="$2"; shift 2 ;;
    --release-client-id-secret-id) release_client_id_secret_id="$2"; shift 2 ;;
    --release-client-secret-secret-id) release_client_secret_secret_id="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for value in "$repository_url" "$release_domain_url" "$release_client_id_secret_id" "$release_client_secret_secret_id"; do
  if [[ -z "$value" ]]; then
    usage >&2
    exit 2
  fi
done

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
repository_dir="$work_dir/repository"

git clone "$repository_url" "$repository_dir"
git -C "$repository_dir" checkout -B main
git -C "$repository_dir" config user.name "OCI App Gateway Release Platform"
git -C "$repository_dir" config user.email "oci-appgateway-release@local"
git -C "$repository_dir" rm -r --ignore-unmatch -- release build_spec.yaml

cp -R "$project_root/release" "$repository_dir/release"
find "$repository_dir/release" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$repository_dir/release" -type f -name "*.pyc" -delete
python3 - "$project_root/platform/templates/build_spec.yaml.tftpl" "$repository_dir/build_spec.yaml" \
  "$release_domain_url" "$release_client_id_secret_id" "$release_client_secret_secret_id" <<'PY'
from pathlib import Path
import sys

template = Path(sys.argv[1]).read_text(encoding="utf-8")
values = {
    "${release_identity_domain_url}": sys.argv[3],
    "${release_client_id_secret_id}": sys.argv[4],
    "${release_client_secret_secret_id}": sys.argv[5],
}
for placeholder, value in values.items():
    template = template.replace(placeholder, value)
Path(sys.argv[2]).write_text(template, encoding="utf-8")
PY

git -C "$repository_dir" add release build_spec.yaml
if git -C "$repository_dir" diff --cached --quiet; then
  echo "Release source is already current. Run the release DevOps build pipeline from the OCI Console."
  exit 0
fi

git -C "$repository_dir" commit -m "Update App Gateway release pipeline source"
git -C "$repository_dir" push -u origin main

echo "Release source published. Run the release DevOps build pipeline from the OCI Console."
