terraform {
  # OCI Resource Manager currently runs Terraform 1.5.x.
  required_version = ">= 1.5.0, < 1.6.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 8.0.0, < 9.0.0"
    }
  }
}
