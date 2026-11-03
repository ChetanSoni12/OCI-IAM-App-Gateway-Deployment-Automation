locals {
  create_vault = var.vault_mode == "Create a new Vault"
  vault_id     = local.create_vault ? oci_kms_vault.platform[0].id : var.existing_vault_id
  vault_key_id = local.create_vault ? oci_kms_key.platform[0].id : var.existing_vault_key_id

  resource_prefix = lower(var.platform_name)
  common_tags = {
    "managed-by" = "oci-iam-appgateway-devops-stack"
    "component"  = "release-platform"
  }
}
