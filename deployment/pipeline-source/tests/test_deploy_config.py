#!/usr/bin/env python3
"""Tests for direct DevOps pipeline parameters and sample detection."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "scripts"))

import deploy  # noqa: E402


class PipelineConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parameters = {
            "ACCESS_MODE": "Public direct",
            "ALLOWED_INGRESS_CIDRS_CSV": "10.0.0.0/24,192.0.2.0/24",
            "ASSIGN_PUBLIC_IP": "true",
            "AVAILABILITY_DOMAIN": "sample:AD-1",
            "COMPARTMENT_OCID": "ocid1.compartment.oc1..example",
            "COMPUTE_IMAGE_OCID": "",
            "COMPUTE_SSH_ALLOWED_CIDR": "not-applicable",
            "COMPUTE_SSH_PUBLIC_KEY": "not-applicable",
            "CONTAINER_SIZE": "Standard",
            "DEPLOYMENT_NAME": "sample-gateway",
            "DEPLOYMENT_VAULT_ID": "ocid1.vault.oc1..example",
            "DEPLOYMENT_VAULT_KEY_ID": "ocid1.key.oc1..example",
            "EXISTING_LOAD_BALANCER_BACKEND_SET_NAME": "",
            "EXISTING_LOAD_BALANCER_ID": "",
            "ENABLE_COMPUTE_SSH": "false",
            "IAM_ADMIN_CLIENT_ID_SECRET_OCID": "ocid1.vaultsecret.oc1..example-id",
            "IAM_ADMIN_CLIENT_SECRET_SECRET_OCID": "ocid1.vaultsecret.oc1..example-secret",
            "IDENTITY_DOMAIN_URL": "https://example.identity.oraclecloud.com",
            "OCIR_IMAGE_TAG": "26.3.33-2608171245",
            "OCIR_PULL_SECRET_OCID": "ocid1.vaultsecret.oc1..example-ocir",
            "OCIR_REPOSITORY_PATH": "iam-appgateway/appgateway",
            "OPERATION": "APPLY",
            "REGION": "us-ashburn-1",
            "RUNTIME_TYPE": "Container Instance",
            "STATE_BUCKET": "sample-appgateway-tfstate",
            "SUBNET_OCID": "ocid1.subnet.oc1..example",
        }

    def test_default_source_is_sample_and_maps_pipeline_values(self) -> None:
        with mock.patch.dict(os.environ, self.parameters, clear=True):
            request, application, smoke = deploy.pipeline_request(SOURCE_ROOT)

        self.assertTrue(smoke)
        self.assertEqual(application["application_name"], "Header Authentication Sample")
        self.assertEqual(request["allowed_ingress_cidrs"], ["10.0.0.0/24", "192.0.2.0/24"])
        self.assertEqual(request["gateway_https_port"], 4443)
        self.assertTrue(request["assign_public_ip"])
        self.assertFalse(request["use_existing_oci_load_balancer"])

    def test_any_changed_config_file_is_custom(self) -> None:
        with mock.patch("deploy.filecmp.cmp", return_value=False):
            self.assertFalse(deploy.is_sample_configuration(SOURCE_ROOT))

    def test_compute_ssh_values_are_mapped(self) -> None:
        parameters = self.parameters | {
            "RUNTIME_TYPE": "Compute Instance",
            "COMPUTE_IMAGE_OCID": "ocid1.image.oc1.iad.example",
            "ENABLE_COMPUTE_SSH": "true",
            "COMPUTE_SSH_PUBLIC_KEY": "ssh-ed25519 AAAAC3NzaExample operator",
            "COMPUTE_SSH_ALLOWED_CIDR": "192.0.2.10/32",
        }
        with mock.patch.dict(os.environ, parameters, clear=True):
            request, _, _ = deploy.pipeline_request(SOURCE_ROOT)

        self.assertTrue(request["enable_compute_ssh"])
        self.assertEqual(request["compute_ssh_allowed_cidr"], "192.0.2.10/32")

    def test_compute_ssh_rejects_unscoped_source(self) -> None:
        parameters = self.parameters | {
            "RUNTIME_TYPE": "Compute Instance",
            "COMPUTE_IMAGE_OCID": "ocid1.image.oc1.iad.example",
            "ENABLE_COMPUTE_SSH": "true",
            "COMPUTE_SSH_PUBLIC_KEY": "ssh-ed25519 AAAAC3NzaExample operator",
            "COMPUTE_SSH_ALLOWED_CIDR": "not-a-cidr",
        }
        with mock.patch.dict(os.environ, parameters, clear=True):
            with self.assertRaisesRegex(ValueError, "COMPUTE_SSH_ALLOWED_CIDR"):
                deploy.pipeline_request(SOURCE_ROOT)

    def test_vault_tls_requires_both_secret_ocids(self) -> None:
        properties = deploy.load_application_properties(SOURCE_ROOT / "config" / "application.properties")
        properties["appgateway_tls_mode"] = "vault"
        properties["appgateway_tls_cert_secret_ocid"] = ""
        with mock.patch("deploy.load_application_properties", return_value=properties):
            with mock.patch.dict(os.environ, self.parameters, clear=True):
                with self.assertRaisesRegex(ValueError, "appgateway_tls_cert_secret_ocid"):
                    deploy.pipeline_request(SOURCE_ROOT)

    def test_tls_choice_does_not_change_sample_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(SOURCE_ROOT / "config", root / "config")
            shutil.copytree(SOURCE_ROOT / "defaults", root / "defaults")
            properties = (root / "config" / "application.properties").read_text()
            properties = properties.replace("appgateway_tls_mode=generated", "appgateway_tls_mode=vault")
            properties = properties.replace("appgateway_tls_cert_secret_ocid=", "appgateway_tls_cert_secret_ocid=ocid1.vaultsecret.cert")
            properties = properties.replace("appgateway_tls_key_secret_ocid=", "appgateway_tls_key_secret_ocid=ocid1.vaultsecret.key")
            (root / "config" / "application.properties").write_text(properties)
            self.assertTrue(deploy.is_sample_configuration(root))

    def test_custom_application_rejects_loopback_origin(self) -> None:
        with mock.patch("deploy.is_sample_configuration", return_value=False):
            with mock.patch.dict(os.environ, self.parameters, clear=True):
                with self.assertRaisesRegex(ValueError, "loopback"):
                    deploy.pipeline_request(SOURCE_ROOT)

    def test_peoplesoft_custom_configuration_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(SOURCE_ROOT / "defaults", root / "defaults")
            shutil.copytree(SOURCE_ROOT / "defaults", root / "config")
            (root / "config" / "application.properties").write_text(
                "application_name=PeopleSoft ERP Test\n"
                "application_landing_url=https://peoplesoft-appgateway.example.com:4443/psc/peoplesoft01_22/EMPLOYEE/ERP/c/NUI_FRAMEWORK.PT_LANDINGPAGE.GBL?\n"
                "application_origin_url=http://192.0.2.10:8000/\n"
                "appgateway_tls_mode=generated\n"
                "appgateway_tls_cert_secret_ocid=\n"
                "appgateway_tls_key_secret_ocid=\n"
            )
            (root / "config" / "app_resources.csv").write_text(
                "ResourceName,ResourceURL,AccessMode\n"
                "default,/.*,oauth\n"
                "psc,/psc/peoplesoft01_22/EMPLOYEE/ERP/c/NUI_FRAMEWORK.PT_LANDINGPAGE.GBL.*,oauth\n"
            )
            (root / "config" / "header_mappings.json").write_text(
                '[{"OAM_REMOTE_USER":"$subject.user.userName"},'
                '{"PS_SSO_UID":"$subject.user.userName"},'
                '{"HTTP_REMOTE_USERID":"$subject.user.userName"},'
                '{"HTTP_OAM_REMOTE_USER":"$subject.user.userName"}]'
            )

            application, _, sample_mode = deploy.validated_application(root)
            resources = deploy.load_resources(root / "config" / "app_resources.csv")
            headers = deploy.load_headers(root / "config" / "header_mappings.json")

            self.assertFalse(sample_mode)
            self.assertEqual(application["application_name"], "PeopleSoft ERP Test")
            self.assertEqual([resource["name"] for resource in resources], ["default", "psc"])
            self.assertEqual(
                [next(iter(header)) for header in headers],
                ["OAM_REMOTE_USER", "PS_SSO_UID", "HTTP_REMOTE_USERID", "HTTP_OAM_REMOTE_USER"],
            )

    def test_generated_certificate_matches_hostname_and_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            certificate, key = deploy.generate_tls_certificate(work, "appgateway.example.com")
            deploy.validate_tls_secret_pair(
                certificate.read_text(), key.read_text(), "appgateway.example.com", work
            )


if __name__ == "__main__":
    unittest.main()
