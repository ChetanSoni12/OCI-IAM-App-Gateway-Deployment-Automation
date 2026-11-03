variable "region" { type = string }
variable "compartment_ocid" { type = string }

variable "deployment_name" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.deployment_name))
    error_message = "deployment_name must be 3-31 characters, start with a lowercase letter, and use only lowercase letters, numbers, and hyphens."
  }
}

variable "availability_domain" { type = string }
variable "subnet_id" { type = string }
variable "target_identity_domain_url" { type = string }
variable "target_iam_admin_client_id_secret_id" { type = string }
variable "target_iam_admin_client_secret_id" { type = string }
variable "deployment_vault_id" { type = string }
variable "deployment_vault_key_id" { type = string }
variable "ocir_pull_secret_id" { type = string }

variable "ocir_repository_path" {
  type    = string
  default = "iam-appgateway/appgateway"
}

variable "ocir_image_tag" { type = string }

variable "runtime_type" {
  type    = string
  default = "Container Instance"
  validation {
    condition     = contains(["Container Instance", "Compute Instance"], var.runtime_type)
    error_message = "runtime_type must be Container Instance or Compute Instance."
  }
}

variable "container_size" {
  type    = string
  default = "Standard"
  validation {
    condition     = contains(["Development", "Standard", "Production"], var.container_size)
    error_message = "container_size must be Development, Standard, or Production."
  }
}

variable "compute_image_ocid" {
  type    = string
  default = ""
}

variable "enable_compute_ssh" {
  type    = bool
  default = false
}

variable "compute_ssh_public_key" {
  type    = string
  default = ""
}

variable "compute_ssh_allowed_cidr" {
  type    = string
  default = ""
}

variable "assign_public_ip" {
  type    = bool
  default = true
}

variable "allowed_ingress_cidrs_csv" {
  type    = string
  default = "0.0.0.0/0"
}

variable "access_mode" {
  type    = string
  default = "Public direct"
  validation {
    condition     = contains(["Public direct", "Existing OCI Load Balancer", "External Load Balancer"], var.access_mode)
    error_message = "access_mode must be Public direct, Existing OCI Load Balancer, or External Load Balancer."
  }
}

variable "existing_load_balancer_id" {
  type    = string
  default = ""
}

variable "existing_load_balancer_backend_set_name" {
  type    = string
  default = ""
}
