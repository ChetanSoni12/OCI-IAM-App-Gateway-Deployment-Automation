"""Secure OCI IAM Domain REST orchestration for an App Gateway deployment."""

from __future__ import annotations

import base64
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class IamError(RuntimeError):
    pass


class IdentityDomain:
    def __init__(self, domain_url: str, client_id: str, client_secret: str) -> None:
        self.domain_url = domain_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = self._token()

    def _token(self) -> str:
        credential = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        payload = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": "urn:opc:idm:__myscopes__"}).encode()
        reply = self.request("POST", "/oauth2/v1/token", payload, {"Authorization": f"Basic {credential}", "Content-Type": "application/x-www-form-urlencoded"}, bearer=False)
        token = reply.get("access_token")
        if not isinstance(token, str) or not token:
            raise IamError("Identity Domain token response did not contain access_token")
        return token

    def request(self, method: str, path: str, payload: bytes | None = None, headers: dict[str, str] | None = None, *, bearer: bool = True) -> dict[str, Any]:
        request_headers = {"Accept": "application/json"}
        if bearer:
            request_headers["Authorization"] = f"Bearer {self.token}"
        request_headers.update(headers or {})
        request = urllib.request.Request(f"{self.domain_url}{path}", data=payload, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60, context=ssl.create_default_context()) as response:
                body = response.read().decode()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise IamError(f"{method} {path} failed: HTTP {error.code}: {detail}") from error

    def json(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request(method, path, json.dumps(payload).encode(), {"Content-Type": "application/scim+json"})

    def create_application(
        self,
        name: str,
        landing_url: str,
        resources: list[dict[str, str]],
        headers: list[dict[str, str]],
    ) -> tuple[str, str]:
        app = self.json("POST", "/admin/v1/Apps", {
            "schemas": [
                "urn:ietf:params:scim:schemas:oracle:idcs:App",
                "urn:ietf:params:scim:schemas:oracle:idcs:extension:requestable:App",
                "urn:ietf:params:scim:schemas:oracle:idcs:extension:managedapp:App",
                "urn:ietf:params:scim:schemas:oracle:idcs:extension:webTierPolicy:App",
            ],
            "displayName": name,
            "description": f"Enterprise application protected by {name} App Gateway",
            "landingPageURL": landing_url,
            "basedOnTemplate": {"value": "CustomEnterpriseAppTemplateId"},
            "isSamlServiceProvider": False, "isOAuthResource": False, "isOAuthClient": False,
            "showInMyApps": False, "isWebTierPolicy": False, "active": True, "isEnterpriseApp": True,
            "urn:ietf:params:scim:schemas:oracle:idcs:extension:requestable:App": {"requestable": False},
            "urn:ietf:params:scim:schemas:oracle:idcs:extension:webTierPolicy:App": {"webTierPolicyAZControl": "local"},
        })
        app_id = app["id"]
        try:
            gateway_app_name = app.get("name")
            if not isinstance(gateway_app_name, str) or not gateway_app_name:
                raise IamError("Enterprise Application response did not contain name required by CloudGateMappings.gatewayApp.name")
            resource_filters: list[dict[str, Any]] = []
            for sequence, resource_spec in enumerate(resources, start=1):
                resource_name = resource_spec["name"]
                resource_url = resource_spec["url"]
                access_mode = resource_spec["access_mode"]
                resource = self.json("POST", "/admin/v1/AppResources", {
                    "schemas": ["urn:ietf:params:scim:schemas:oracle:idcs:AppResource"],
                    "name": resource_name,
                    "resourceURL": resource_url,
                    "isRegex": True,
                    "description": f"Protected resource for {name}",
                    "app": {"value": app_id},
                })
                resource_id = resource["id"]
                self.json("PATCH", f"/admin/v1/Apps/{app_id}", {
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                    "Operations": [{
                        "op": "add",
                        "path": "urn:ietf:params:scim:schemas:oracle:idcs:extension:enterpriseApp:App:appResources",
                        "value": [{"value": resource_id}],
                    }],
                })
                filter_entry: dict[str, Any] = {
                    "filter": resource_url,
                    "comment": f"{resource_name} policy",
                    "resourceRefId": resource_id,
                    "resourceRefName": resource_name,
                    "type": "regex",
                    "sequence": str(sequence),
                    "method": access_mode,
                }
                if access_mode == "oauth":
                    filter_entry["headers"] = headers
                resource_filters.append(filter_entry)

            web_tier_policy = {
                "cloudgatePolicy": {
                    "version": "2.6",
                    "requireSecureCookies": True,
                    "allowCors": True,
                    "disableAuthorize": True,
                    "webtierPolicy": [{
                        "policyName": "default",
                        "comment": "Webtier policy",
                        "resourceFilters": resource_filters,
                    }],
                },
            }
            patch = {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": [
                {"op": "add", "path": "urn:ietf:params:scim:schemas:oracle:idcs:extension:webTierPolicy:App:webTierPolicyJson", "value": json.dumps(web_tier_policy, separators=(",", ":"))},
            ]}
            self.json("PATCH", f"/admin/v1/Apps/{app_id}", patch)
            return app_id, gateway_app_name
        except Exception:
            try:
                self.request("DELETE", f"/admin/v1/Apps/{app_id}?forceDelete=true")
            except IamError:
                pass
            raise

    def create_gateway(self, name: str, hostname: str, port: int, app_id: str, gateway_app_name: str, origin_url: str) -> tuple[str, str, str]:
        gate = self.json("POST", "/admin/v1/CloudGates", {"schemas": ["urn:ietf:params:scim:schemas:oracle:idcs:CloudGate"], "displayName": name, "type": "gateway", "active": True})
        gate_id = gate["id"]
        try:
            client = gate["oauthClient"]
            self.json("PATCH", f"/admin/v1/CloudGates/{gate_id}", {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": [{"op": "replace", "path": "active", "value": True}]})
            server = self.json("POST", "/admin/v1/CloudGateServers", {
                "schemas": ["urn:ietf:params:scim:schemas:oracle:idcs:CloudGateServer"],
                "description": f"Server block for {name}",
                "displayName": f"{name}-server",
                "hostName": hostname,
                "port": port,
                "ssl": True,
                "nginxSettings": "ssl_certificate /usr/local/nginx/conf/cert.pem;\nssl_certificate_key /usr/local/nginx/conf/key.pem;\nssl_protocols TLSv1.2 TLSv1.3;\nssl_ciphers HIGH:!aNULL:!MD5;",
                "cloudGate": {"value": gate_id},
            })
            self.json("POST", "/admin/v1/CloudGateMappings", {
                "schemas": ["urn:ietf:params:scim:schemas:oracle:idcs:CloudGateMapping"],
                "description": f"{name} mapping",
                "resourcePrefix": "/",
                "proxyPass": origin_url,
                "policyName": "default",
                "server": {"value": server["id"]},
                "cloudGate": {"value": gate_id},
                "gatewayApp": {"value": app_id, "name": gateway_app_name},
            })
            return gate_id, client["clientId"], client["clientSecret"]
        except Exception:
            try:
                self.request("DELETE", f"/admin/v1/CloudGates/{gate_id}?forceDelete=true")
            except IamError:
                pass
            raise

    def delete_gateway_and_application(self, gateway_id: str, application_id: str) -> None:
        """Remove resources created by one failed or destroyed deployment."""
        try:
            self.json("PATCH", f"/admin/v1/CloudGates/{gateway_id}", {
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [{"op": "replace", "path": "active", "value": False}],
            })
        except IamError:
            pass

        time.sleep(5)
        mappings = self.request("GET", "/admin/v1/CloudGateMappings?attributes=id,cloudGate&count=200").get("Resources", [])
        servers = self.request("GET", "/admin/v1/CloudGateServers?attributes=id,cloudGate&count=200").get("Resources", [])

        def delete_with_retry(path: str, resource_id: str) -> None:
            for attempt in range(8):
                try:
                    self.request("DELETE", f"{path}/{resource_id}?forceDelete=true")
                    return
                except IamError:
                    if attempt == 7:
                        raise
                    time.sleep(10)

        for mapping in mappings:
            if mapping.get("cloudGate", {}).get("value") == gateway_id:
                delete_with_retry("/admin/v1/CloudGateMappings", mapping["id"])
        for server in servers:
            if server.get("cloudGate", {}).get("value") == gateway_id:
                delete_with_retry("/admin/v1/CloudGateServers", server["id"])

        delete_with_retry("/admin/v1/CloudGates", gateway_id)
        try:
            self.json("PATCH", f"/admin/v1/Apps/{application_id}", {
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [{"op": "replace", "path": "active", "value": False}],
            })
        except IamError:
            pass
        delete_with_retry("/admin/v1/Apps", application_id)

    def wallet_tool_url(self) -> str:
        metadata = self.request("GET", "/admin/v1/LatestBinaryFileInfoVersionRetriever")
        for item in metadata.get("Resources", []):
            if "idcs-appgateway-wallet-tool" in item.get("fileName", ""):
                return urllib.parse.urljoin(f"{self.domain_url}/", item["downloadURL"])
        raise IamError("IAM domain did not return an App Gateway wallet-tool package")
