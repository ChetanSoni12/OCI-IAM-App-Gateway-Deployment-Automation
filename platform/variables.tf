variable "region" {
  description = "OCI region for the shared release platform."
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment that owns the release platform resources."
  type        = string
}

variable "tenancy_ocid" {
  description = "Tenancy OCID. Required to create the DevOps dynamic group policy."
  type        = string
}

variable "platform_name" {
  description = "Short prefix for shared App Gateway release resources."
  type        = string
  default     = "iam-appgateway"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.platform_name))
    error_message = "platform_name must start with a lowercase letter and contain only lowercase letters, numbers, and hyphens."
  }
}

variable "release_identity_domain_url" {
  description = "IAM domain used only by the internal release pipeline to retrieve App Gateway packages."
  type        = string

  validation {
    condition     = can(regex("^https://", var.release_identity_domain_url))
    error_message = "release_identity_domain_url must start with https://."
  }
}

variable "release_client_id" {
  description = "Client ID for the dedicated release IAM application."
  type        = string
  sensitive   = true
}

variable "release_client_secret" {
  description = "Client secret for the dedicated release IAM application."
  type        = string
  sensitive   = true
}

variable "ocir_pull_username" {
  description = "OCIR username used by future Container Instance deployments to pull the private App Gateway image."
  type        = string
  sensitive   = true
}

variable "ocir_pull_auth_token" {
  description = "OCIR auth token used by future Container Instance deployments to pull the private App Gateway image."
  type        = string
  sensitive   = true
}

variable "vault_mode" {
  description = "Create a new Vault for platform secrets or use an existing Vault and key."
  type        = string
  default     = "Create a new Vault"

  validation {
    condition     = contains(["Create a new Vault", "Use existing Vault"], var.vault_mode)
    error_message = "vault_mode must be Create a new Vault or Use existing Vault."
  }
}

variable "vault_name" {
  description = "Name for the new platform Vault."
  type        = string
  default     = "iam-appgateway-release-vault"
}

variable "vault_key_name" {
  description = "Name for the key that encrypts platform secrets."
  type        = string
  default     = "iam-appgateway-release-key"
}

variable "existing_vault_id" {
  description = "Existing Vault OCID when vault_mode is Use existing Vault."
  type        = string
  default     = ""
}

variable "existing_vault_key_id" {
  description = "Existing Vault encryption key OCID when vault_mode is Use existing Vault."
  type        = string
  default     = ""
}

variable "ocir_repository_name" {
  description = "Private OCIR repository name for approved App Gateway images."
  type        = string
  default     = "iam-appgateway/appgateway"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._/-]{1,200}$", var.ocir_repository_name))
    error_message = "ocir_repository_name must be a lowercase OCI Container Registry repository path."
  }
}

variable "create_platform_policies" {
  description = "Create least-privilege policies for the DevOps build pipeline."
  type        = bool
  default     = true
}

