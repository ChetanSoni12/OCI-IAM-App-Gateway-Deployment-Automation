#!/usr/bin/env python3
"""Regression tests for the frozen Enterprise Application contract."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "scripts"))

from iam_domain import IdentityDomain  # noqa: E402


class RecordingDomain(IdentityDomain):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.resource_number = 0

    def json(self, method: str, path: str, payload: dict) -> dict:
        self.calls.append((method, path, payload))
        if method == "POST" and path == "/admin/v1/Apps":
            return {"id": "app-id", "name": "app-internal-name"}
        if method == "POST" and path == "/admin/v1/AppResources":
            self.resource_number += 1
            return {"id": f"resource-{self.resource_number}"}
        return {}

    def request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return {}


class EnterpriseApplicationContractTests(unittest.TestCase):
    def test_matches_frozen_resources_and_headers(self) -> None:
        domain = RecordingDomain()
        resources = [
            {"name": "root", "url": "/.*", "access_mode": "oauth"},
            {"name": "static", "url": "/static/.*", "access_mode": "public"},
            {"name": "health", "url": "/health.*", "access_mode": "public"},
            {"name": "logout", "url": "/logout", "access_mode": "oauth"},
        ]
        headers = [
            {"iv-user": "$subject.user.userName"},
            {"x-authenticated-user": "$subject.user.userName"},
            {"x-authenticated-email": "$subject.user.primaryEmail"},
        ]

        app_id, app_name = domain.create_application(
            "Header Authentication Sample",
            "https://appgateway.example.com:4443/",
            resources,
            headers,
        )

        self.assertEqual((app_id, app_name), ("app-id", "app-internal-name"))
        app_payload = domain.calls[0][2]
        self.assertEqual(
            app_payload["schemas"],
            [
                "urn:ietf:params:scim:schemas:oracle:idcs:App",
                "urn:ietf:params:scim:schemas:oracle:idcs:extension:requestable:App",
                "urn:ietf:params:scim:schemas:oracle:idcs:extension:managedapp:App",
                "urn:ietf:params:scim:schemas:oracle:idcs:extension:webTierPolicy:App",
            ],
        )
        self.assertFalse(app_payload["isWebTierPolicy"])
        self.assertEqual(
            app_payload["urn:ietf:params:scim:schemas:oracle:idcs:extension:webTierPolicy:App"],
            {"webTierPolicyAZControl": "local"},
        )

        resource_calls = [call for call in domain.calls if call[0] == "POST" and call[1] == "/admin/v1/AppResources"]
        self.assertEqual([call[2]["resourceURL"] for call in resource_calls], [resource["url"] for resource in resources])

        final_patch = domain.calls[-1][2]
        paths = [operation["path"] for operation in final_patch["Operations"]]
        self.assertEqual(paths, ["urn:ietf:params:scim:schemas:oracle:idcs:extension:webTierPolicy:App:webTierPolicyJson"])
        policy = json.loads(final_patch["Operations"][0]["value"])
        filters = policy["cloudgatePolicy"]["webtierPolicy"][0]["resourceFilters"]
        self.assertEqual([item["filter"] for item in filters], [resource["url"] for resource in resources])
        self.assertEqual(filters[0]["headers"], headers)
        self.assertNotIn("headers", filters[1])
        self.assertNotIn("headers", filters[2])
        self.assertEqual(filters[3]["headers"], headers)

    def test_gateway_server_and_mapping_match_frozen_contract(self) -> None:
        domain = RecordingDomain()

        def response(method: str, path: str, payload: dict) -> dict:
            domain.calls.append((method, path, payload))
            if path == "/admin/v1/CloudGates" and method == "POST":
                return {"id": "gateway-id", "oauthClient": {"clientId": "client-id", "clientSecret": "client-secret"}}
            if path == "/admin/v1/CloudGateServers" and method == "POST":
                return {"id": "server-id"}
            return {}

        domain.json = response  # type: ignore[method-assign]
        result = domain.create_gateway(
            "sample-gateway", "appgateway.example.com", 4443,
            "app-id", "app-internal-name", "http://127.0.0.1:8080/",
        )

        self.assertEqual(result, ("gateway-id", "client-id", "client-secret"))
        server_payload = next(call[2] for call in domain.calls if call[1] == "/admin/v1/CloudGateServers")
        self.assertEqual(server_payload["displayName"], "sample-gateway-server")
        self.assertEqual(server_payload["description"], "Server block for sample-gateway")
        mapping_payload = next(call[2] for call in domain.calls if call[1] == "/admin/v1/CloudGateMappings")
        self.assertEqual(mapping_payload["description"], "sample-gateway mapping")
        self.assertEqual(mapping_payload["gatewayApp"], {"value": "app-id", "name": "app-internal-name"})


if __name__ == "__main__":
    unittest.main()
