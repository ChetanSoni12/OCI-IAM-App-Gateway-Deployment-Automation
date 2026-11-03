variable "region" { type = string }
variable "compartment_ocid" { type = string }
variable "availability_domain" { type = string }
variable "deployment_name" { type = string }
variable "runtime_type" { type = string }
variable "subnet_id" { type = string }
variable "assign_public_ip" { type = bool }
variable "allowed_ingress_cidrs" { type = list(string) }
variable "gateway_https_port" { type = number }
variable "container_size" { type = string }
variable "appgateway_image" { type = string }
variable "smoke_backend_image" { type = string }
variable "deploy_smoke_backend" { type = bool }
variable "target_identity_domain_url" { type = string }
variable "wallet_secret_id" {
  type      = string
  sensitive = true
}

variable "tls_cert_secret_id" {
  type      = string
  sensitive = true
}

variable "tls_key_secret_id" {
  type      = string
  sensitive = true
}

variable "ocir_pull_secret_id" {
  type      = string
  sensitive = true
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
variable "use_existing_oci_load_balancer" { type = bool }
variable "existing_load_balancer_id" {
  type    = string
  default = ""
}
variable "existing_load_balancer_backend_set_name" {
  type    = string
  default = ""
}
variable "external_load_balancer_managed" { type = bool }
