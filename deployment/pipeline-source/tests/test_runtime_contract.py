#!/usr/bin/env python3
"""Static contract checks for the Compute runtime bootstrap."""

from pathlib import Path
import unittest


RUNTIME = Path(__file__).resolve().parents[1] / "runtime"


class ComputeRuntimeContractTests(unittest.TestCase):
    def test_compute_shape_and_cloud_init_contract(self) -> None:
        terraform = (RUNTIME / "main.tf").read_text()
        cloud_init = (RUNTIME / "compute-cloud-init.sh.tftpl").read_text()

        self.assertIn('shape               = "VM.Standard.E4.Flex"', terraform)
        self.assertIn("ssh_authorized_keys", terraform)
        self.assertIn('destination_port_range {\n      min = 22', terraform)
        self.assertIn("--auth instance_principal", cloud_init)
        self.assertIn("podman login", cloud_init)
        self.assertIn("iam-appgateway.service", cloud_init)
        self.assertIn("/var/log/iam-appgateway-bootstrap.log", cloud_init)
        self.assertIn("python36-oci-cli", cloud_init)
        self.assertNotIn("podman oci-cli jq", cloud_init)
        self.assertIn("--entrypoint id '${image}' -u nginx", cloud_init)
        self.assertIn('chown "$appgateway_uid:$appgateway_gid"', cloud_init)
        self.assertIn("--add-port='${gateway_https_port}/tcp'", cloud_init)
        self.assertIn("gateway_https_port  = var.gateway_https_port", terraform)

    def test_cloud_init_never_embeds_ocir_credentials(self) -> None:
        cloud_init = (RUNTIME / "compute-cloud-init.sh.tftpl").read_text()
        self.assertIn("ocir_secret_id", cloud_init)
        self.assertNotIn("ocir_username", cloud_init)
        self.assertNotIn("ocir_auth_token", cloud_init)


if __name__ == "__main__":
    unittest.main()
