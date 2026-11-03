#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  bootstrap-devops.sh [--region <region>] [--compartment-ocid <ocid>] [--config-dir <directory>]
  bootstrap-devops.sh --repository-url <OCI DevOps repository URL> [--config-dir <directory>]

The first form creates one isolated DevOps project, private source repository,
pipeline, logs, notification topic, and Terraform state bucket. It prompts for
the deployment values once and stores the three sensitive values in the Vault
that you select. The second form updates source and application configuration
in an existing DevOps repository only.
EOF
  exit 2
}

region=""
compartment_ocid=""
repository_url=""
config_dir=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) region="${2:-}"; shift 2 ;;
    --compartment-ocid) compartment_ocid="${2:-}"; shift 2 ;;
    --repository-url) repository_url="${2:-}"; shift 2 ;;
    --config-dir) config_dir="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

for tool in git jq oci python3; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "$script_dir/pipeline-source" ]]; then
  bundle_root="$script_dir"
else
  bundle_root="$(cd "$script_dir/.." && pwd)"
fi
source_root="$bundle_root/pipeline-source"
[[ -d "$source_root" ]] || { echo "pipeline-source directory is missing." >&2; exit 1; }
config_dir="${config_dir:-$source_root/config}"
config_dir="$(cd "$config_dir" && pwd)"
for file in application.properties app_resources.csv header_mappings.json; do
  [[ -f "$config_dir/$file" ]] || { echo "Configuration file is missing: $config_dir/$file" >&2; exit 1; }
done

configuration_mode="$(python3 - "$source_root" "$config_dir" <<'PY'
import sys
from pathlib import Path

source_root = Path(sys.argv[1])
config_dir = Path(sys.argv[2])
sys.path.insert(0, str(source_root / "scripts"))
import deploy

with __import__("tempfile").TemporaryDirectory(prefix="appgateway-config-") as directory:
    validation_root = Path(directory)
    (validation_root / "config").symlink_to(config_dir, target_is_directory=True)
    (validation_root / "defaults").symlink_to(source_root / "defaults", target_is_directory=True)
    _, _, sample = deploy.validated_application(validation_root)
print("sample" if sample else "custom")
PY
)"
if [[ "$configuration_mode" == "sample" ]]; then
  echo "Configuration mode: SAMPLE HEADER APPLICATION"
else
  echo "Configuration mode: CUSTOM APPLICATION (the bundled sample backend will not be deployed)"
fi

publish_source() {
  local url="$1" work_dir repository_dir
  work_dir="$(mktemp -d)"
  repository_dir="$work_dir/repository"
  git clone "$url" "$repository_dir"
  (
    cd "$repository_dir"
    git checkout -B main
    cp -R "$source_root/." .
    rm -rf config
    mkdir -p config
    cp "$config_dir/application.properties" "$config_dir/app_resources.csv" "$config_dir/header_mappings.json" config/
    git config user.name "OCI App Gateway Deployment Automation"
    git config user.email "oci-appgateway-deployment@localhost"
    git add .
    if git diff --cached --quiet; then
      echo "Application deployment source and configuration are already current."
    else
      git commit -m "Configure OCI IAM App Gateway deployment"
      git push -u origin main
      echo "Application deployment source and configuration were published."
    fi
  )
  rm -rf "$work_dir"
}

if [[ -n "$repository_url" ]]; then
  publish_source "$repository_url"
  exit 0
fi

command -v terraform >/dev/null || { echo "Missing required tool: terraform" >&2; exit 1; }

read_value() {
  local label="$1" default_value="${2:-}" value
  if [[ -n "$default_value" ]]; then
    read -r -p "$label [$default_value]: " value
    printf '%s' "${value:-$default_value}"
  else
    read -r -p "$label: " value
    printf '%s' "$value"
  fi
}

read_secret() {
  local label="$1" value
  read -r -s -p "$label: " value
  echo >&2
  printf '%s' "$value"
}

region="${region:-$(read_value 'OCI region' "${OCI_REGION:-us-ashburn-1}")}" 
compartment_ocid="${compartment_ocid:-$(read_value 'Deployment compartment OCID')}"
deployment_name="$(read_value 'Deployment name' 'iam-appgateway')"
[[ "$deployment_name" =~ ^[a-z][a-z0-9-]{2,30}$ ]] || {
  echo "Deployment name must be 3-31 characters, start with a lowercase letter, and contain only lowercase letters, numbers, and hyphens." >&2
  exit 1
}
availability_domain="$(read_value 'Availability domain')"
subnet_id="$(read_value 'Existing subnet OCID')"
runtime_type="$(read_value 'Runtime type: Container Instance or Compute Instance' 'Container Instance')"
container_size="$(read_value 'Runtime size: Development, Standard, or Production' 'Standard')"
access_mode="$(read_value 'Gateway access: Public direct, Existing OCI Load Balancer, or External Load Balancer' 'Public direct')"
assign_public_ip="$(read_value 'Assign a public IP: true or false' 'true')"
allowed_ingress_cidrs_csv="$(read_value 'Allowed ingress CIDRs, comma separated (use /32 for one client)')"
python3 - "$allowed_ingress_cidrs_csv" <<'PY'
import ipaddress
import sys

values = [value.strip() for value in sys.argv[1].split(",") if value.strip()]
if not values:
    raise SystemExit("At least one allowed ingress CIDR is required")
try:
    for value in values:
        ipaddress.ip_network(value, strict=False)
except ValueError as error:
    raise SystemExit(f"Allowed ingress CIDRs contain an invalid value: {error}")
PY
identity_domain_url="$(read_value 'OCI IAM Identity Domain URL')"
vault_id="$(read_value 'Existing Vault OCID')"
vault_key_id="$(read_value 'Existing Vault key OCID')"
ocir_repository_path="$(read_value 'OCIR repository path' 'iam-appgateway/appgateway')"
ocir_image_tag="$(read_value 'Approved App Gateway image tag')"

compute_image_ocid=""
enable_compute_ssh="false"
compute_ssh_public_key=""
compute_ssh_allowed_cidr=""
if [[ "$runtime_type" == "Compute Instance" ]]; then
  compute_image_ocid="$(read_value 'Oracle Linux 8 x86_64 compute image OCID')"
  enable_compute_ssh="$(read_value 'Enable optional SSH access: true or false' 'false')"
  if [[ "$enable_compute_ssh" == "true" ]]; then
    compute_ssh_public_key_file="$(read_value 'SSH public key file path')"
    compute_ssh_public_key_file="${compute_ssh_public_key_file/#\~/$HOME}"
    [[ -f "$compute_ssh_public_key_file" ]] || { echo "SSH public key file was not found: $compute_ssh_public_key_file" >&2; exit 1; }
    compute_ssh_public_key="$(tr -d '\r\n' < "$compute_ssh_public_key_file")"
    compute_ssh_allowed_cidr="$(read_value 'Single CIDR allowed to use SSH (use /32 for one address)')"
  fi
fi

existing_load_balancer_id=""
existing_load_balancer_backend_set_name=""
if [[ "$access_mode" == "Existing OCI Load Balancer" ]]; then
  existing_load_balancer_id="$(read_value 'Existing OCI Load Balancer OCID')"
  existing_load_balancer_backend_set_name="$(read_value 'Existing backend set name')"
fi

iam_admin_client_id="$(read_secret 'IAM administrator confidential-app client ID')"
iam_admin_client_secret="$(read_secret 'IAM administrator confidential-app client secret')"
ocir_username="$(read_secret 'OCIR pull username')"
ocir_auth_token="$(read_secret 'OCIR auth token')"

[[ -n "$compartment_ocid" && -n "$deployment_name" && -n "$availability_domain" && -n "$subnet_id" ]] || { echo "Deployment name, compartment, availability domain, and subnet are required." >&2; exit 1; }
[[ -n "$identity_domain_url" && -n "$vault_id" && -n "$vault_key_id" && -n "$ocir_image_tag" ]] || { echo "Identity Domain, Vault, Vault key, and image tag are required." >&2; exit 1; }
[[ -n "$iam_admin_client_id" && -n "$iam_admin_client_secret" && -n "$ocir_username" && -n "$ocir_auth_token" ]] || { echo "IAM and OCIR credentials are required." >&2; exit 1; }
[[ "$runtime_type" == "Container Instance" || "$runtime_type" == "Compute Instance" ]] || { echo "Runtime type must be Container Instance or Compute Instance." >&2; exit 1; }
[[ "$container_size" == "Development" || "$container_size" == "Standard" || "$container_size" == "Production" ]] || { echo "Runtime size must be Development, Standard, or Production." >&2; exit 1; }
[[ "$access_mode" == "Public direct" || "$access_mode" == "Existing OCI Load Balancer" || "$access_mode" == "External Load Balancer" ]] || { echo "Gateway access mode is not valid." >&2; exit 1; }
[[ "$assign_public_ip" == "true" || "$assign_public_ip" == "false" ]] || { echo "Assign public IP must be true or false." >&2; exit 1; }
[[ "$enable_compute_ssh" == "true" || "$enable_compute_ssh" == "false" ]] || { echo "Enable Compute SSH must be true or false." >&2; exit 1; }

subnet_prohibits_public_ip="$(oci network subnet get --subnet-id "$subnet_id" --query 'data."prohibit-public-ip-on-vnic"' --raw-output)"
if [[ "$subnet_prohibits_public_ip" == "true" ]]; then
  if [[ "$assign_public_ip" == "true" ]]; then
    echo "Selected subnet prohibits public IPs; Assign public IP has been set to false."
    assign_public_ip="false"
  fi
  [[ "$access_mode" != "Public direct" ]] || { echo "A private subnet cannot use Public direct access. Choose Existing OCI Load Balancer or External Load Balancer." >&2; exit 1; }
  if [[ "$runtime_type" == "Compute Instance" && "$enable_compute_ssh" == "true" ]]; then
    echo "Private Compute SSH requires an existing OCI Bastion session or another private administrative path. Bootstrap does not create a Bastion."
  fi
fi
[[ "$access_mode" != "Public direct" || "$assign_public_ip" == "true" ]] || { echo "Public direct access requires a public IP. Enable it or choose a load-balancer access mode." >&2; exit 1; }

if [[ "$runtime_type" == "Compute Instance" ]]; then
  [[ -n "$compute_image_ocid" ]] || { echo "Compute Instance requires an Oracle Linux 8 x86_64 image OCID." >&2; exit 1; }
  if [[ "$enable_compute_ssh" == "true" ]]; then
    [[ "$compute_ssh_public_key" =~ ^(ssh-rsa|ssh-ed25519|ecdsa-sha2-) ]] || { echo "SSH public key must be in OpenSSH public-key format." >&2; exit 1; }
    python3 - "$compute_ssh_allowed_cidr" <<'PY'
import ipaddress
import sys

try:
    network = ipaddress.ip_network(sys.argv[1], strict=False)
    if network.prefixlen == 0:
        raise ValueError("an unrestricted /0 network is not allowed")
except ValueError as error:
    raise SystemExit(f"SSH allowed source must be a valid CIDR: {error}")
PY
  fi
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

create_secret() {
  local secret_name="$1" secret_value="$2" content_file response
  content_file="$work_dir/${secret_name}.json"
  jq -n \
    --arg compartment "$compartment_ocid" \
    --arg vault "$vault_id" \
    --arg key "$vault_key_id" \
    --arg name "$secret_name" \
    --arg content "$(printf '%s' "$secret_value" | base64 | tr -d '\n')" \
    '{compartmentId: $compartment, vaultId: $vault, keyId: $key, secretName: $name, secretContentContent: $content}' > "$content_file"
  response="$(oci vault secret create-base64 --from-json "file://$content_file" --wait-for-state ACTIVE --max-wait-seconds 300)"
  jq -er '.data.id' <<<"$response"
}

suffix="$(date +%s)-$RANDOM"
echo "Creating deployment secrets in the selected Vault..."
iam_admin_client_id_secret_id="$(create_secret "${deployment_name}-iam-admin-client-id-${suffix}" "$iam_admin_client_id")"
iam_admin_client_secret_secret_id="$(create_secret "${deployment_name}-iam-admin-client-secret-${suffix}" "$iam_admin_client_secret")"
ocir_pull_secret_id="$(create_secret "${deployment_name}-ocir-pull-${suffix}" "$(jq -nc --arg username "$ocir_username" --arg password "$ocir_auth_token" '{username: $username, password: $password}')")"

tfvars="$work_dir/foundation.auto.tfvars.json"
jq -n \
  --arg region "$region" \
  --arg compartment_ocid "$compartment_ocid" \
  --arg deployment_name "$deployment_name" \
  --arg availability_domain "$availability_domain" \
  --arg subnet_id "$subnet_id" \
  --arg target_identity_domain_url "${identity_domain_url%/}" \
  --arg target_iam_admin_client_id_secret_id "$iam_admin_client_id_secret_id" \
  --arg target_iam_admin_client_secret_id "$iam_admin_client_secret_secret_id" \
  --arg deployment_vault_id "$vault_id" \
  --arg deployment_vault_key_id "$vault_key_id" \
  --arg ocir_pull_secret_id "$ocir_pull_secret_id" \
  --arg ocir_repository_path "$ocir_repository_path" \
  --arg ocir_image_tag "$ocir_image_tag" \
  --arg runtime_type "$runtime_type" \
  --arg container_size "$container_size" \
  --arg compute_image_ocid "$compute_image_ocid" \
  --arg compute_ssh_public_key "$compute_ssh_public_key" \
  --arg compute_ssh_allowed_cidr "$compute_ssh_allowed_cidr" \
  --arg access_mode "$access_mode" \
  --arg existing_load_balancer_id "$existing_load_balancer_id" \
  --arg existing_load_balancer_backend_set_name "$existing_load_balancer_backend_set_name" \
  --arg allowed_ingress_cidrs_csv "$allowed_ingress_cidrs_csv" \
  --argjson assign_public_ip "$assign_public_ip" \
  --argjson enable_compute_ssh "$enable_compute_ssh" \
  '{region: $region, compartment_ocid: $compartment_ocid, deployment_name: $deployment_name, availability_domain: $availability_domain, subnet_id: $subnet_id, target_identity_domain_url: $target_identity_domain_url, target_iam_admin_client_id_secret_id: $target_iam_admin_client_id_secret_id, target_iam_admin_client_secret_id: $target_iam_admin_client_secret_id, deployment_vault_id: $deployment_vault_id, deployment_vault_key_id: $deployment_vault_key_id, ocir_pull_secret_id: $ocir_pull_secret_id, ocir_repository_path: $ocir_repository_path, ocir_image_tag: $ocir_image_tag, runtime_type: $runtime_type, container_size: $container_size, compute_image_ocid: $compute_image_ocid, enable_compute_ssh: $enable_compute_ssh, compute_ssh_public_key: $compute_ssh_public_key, compute_ssh_allowed_cidr: $compute_ssh_allowed_cidr, access_mode: $access_mode, existing_load_balancer_id: $existing_load_balancer_id, existing_load_balancer_backend_set_name: $existing_load_balancer_backend_set_name, allowed_ingress_cidrs_csv: $allowed_ingress_cidrs_csv, assign_public_ip: $assign_public_ip}' > "$tfvars"

state_root="${APPGATEWAY_BOOTSTRAP_HOME:-$HOME/.oci-iam-appgateway-devops}/$deployment_name"
mkdir -p "$state_root"
state_file="$state_root/foundation.tfstate"
echo "Creating or updating the isolated DevOps foundation..."
terraform -chdir="$bundle_root/foundation-stack" init -input=false
terraform -chdir="$bundle_root/foundation-stack" apply -auto-approve -input=false -state="$state_file" -var-file="$tfvars"
repository_url="$(terraform -chdir="$bundle_root/foundation-stack" output -state="$state_file" -raw application_source_repository_url)"

publish_source "$repository_url"
pipeline_id="$(terraform -chdir="$bundle_root/foundation-stack" output -state="$state_file" -raw application_pipeline_id)"
echo
echo "Bootstrap complete. In OCI Console, open DevOps build pipeline: $pipeline_id"
echo "Choose Start manual run. The pipeline parameters are pre-filled and can be reviewed before it runs."
