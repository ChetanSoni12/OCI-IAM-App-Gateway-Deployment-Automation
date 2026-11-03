locals {
  prefix            = var.deployment_name
  state_bucket_name = "${var.deployment_name}-appgateway-tfstate"
  tags = {
    "managed-by"      = "oci-iam-appgateway-devops-stack"
    "component"       = "application-deployment"
    "deployment-name" = var.deployment_name
  }

  pipeline_parameters = {
    ACCESS_MODE                             = { value = var.access_mode, description = "Public direct, Existing OCI Load Balancer, or External Load Balancer." }
    ALLOWED_INGRESS_CIDRS_CSV               = { value = var.allowed_ingress_cidrs_csv, description = "Comma-separated CIDRs allowed to reach App Gateway." }
    ASSIGN_PUBLIC_IP                        = { value = tostring(var.assign_public_ip), description = "Assign a public IPv4 address to the runtime VNIC." }
    AVAILABILITY_DOMAIN                     = { value = var.availability_domain, description = "Availability Domain for the selected runtime." }
    COMPARTMENT_OCID                        = { value = var.compartment_ocid, description = "Compartment containing the runtime and Vault secrets." }
    COMPUTE_IMAGE_OCID                      = { value = var.compute_image_ocid != "" ? var.compute_image_ocid : "not-applicable", description = "Oracle Linux image OCID used only for Compute Instance." }
    COMPUTE_SSH_ALLOWED_CIDR                = { value = var.compute_ssh_allowed_cidr != "" ? var.compute_ssh_allowed_cidr : "not-applicable", description = "Single CIDR allowed to use SSH when Compute SSH is enabled." }
    COMPUTE_SSH_PUBLIC_KEY                  = { value = var.compute_ssh_public_key != "" ? var.compute_ssh_public_key : "not-applicable", description = "OpenSSH public key installed only when Compute SSH is enabled." }
    CONTAINER_SIZE                          = { value = var.container_size, description = "Container or Compute resource profile." }
    DEPLOYMENT_NAME                         = { value = var.deployment_name, description = "Unique name for this isolated App Gateway deployment." }
    DEPLOYMENT_VAULT_ID                     = { value = var.deployment_vault_id, description = "Vault OCID used for the generated wallet and TLS secrets." }
    DEPLOYMENT_VAULT_KEY_ID                 = { value = var.deployment_vault_key_id, description = "Vault key OCID used for generated secrets." }
    EXISTING_LOAD_BALANCER_BACKEND_SET_NAME = { value = var.existing_load_balancer_backend_set_name != "" ? var.existing_load_balancer_backend_set_name : "not-applicable", description = "Existing OCI Load Balancer backend set when that access mode is selected." }
    EXISTING_LOAD_BALANCER_ID               = { value = var.existing_load_balancer_id != "" ? var.existing_load_balancer_id : "not-applicable", description = "Existing OCI Load Balancer OCID when that access mode is selected." }
    ENABLE_COMPUTE_SSH                      = { value = tostring(var.enable_compute_ssh), description = "Enable optional SSH access to the Compute runtime." }
    IAM_ADMIN_CLIENT_ID_SECRET_OCID         = { value = var.target_iam_admin_client_id_secret_id, description = "Vault secret OCID containing the IAM administrator client ID." }
    IAM_ADMIN_CLIENT_SECRET_SECRET_OCID     = { value = var.target_iam_admin_client_secret_id, description = "Vault secret OCID containing the IAM administrator client secret." }
    IDENTITY_DOMAIN_URL                     = { value = trimsuffix(var.target_identity_domain_url, "/"), description = "Target OCI IAM Identity Domain URL." }
    OCIR_IMAGE_TAG                          = { value = var.ocir_image_tag, description = "Approved App Gateway image tag." }
    OCIR_PULL_SECRET_OCID                   = { value = var.ocir_pull_secret_id, description = "Vault secret OCID containing the OCIR username and auth token." }
    OCIR_REPOSITORY_PATH                    = { value = var.ocir_repository_path, description = "Private OCIR repository path without registry host or tag." }
    OPERATION                               = { value = "APPLY", description = "APPLY creates or updates the deployment; DESTROY removes it." }
    REGION                                  = { value = var.region, description = "OCI region hosting the runtime." }
    RUNTIME_TYPE                            = { value = var.runtime_type, description = "Container Instance or Compute Instance." }
    STATE_BUCKET                            = { value = local.state_bucket_name, description = "Private bucket used only for Terraform state and deployment metadata." }
    SUBNET_OCID                             = { value = var.subnet_id, description = "Existing subnet hosting the App Gateway runtime." }
  }
}
