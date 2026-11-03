#!/usr/bin/env python3
"""DevOps entry point for one OCI IAM App Gateway deployment."""

from __future__ import annotations

import base64
import csv
import filecmp
import hashlib
import ipaddress
import io
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, urlparse

from iam_domain import IamError, IdentityDomain


def run(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        args,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{' '.join(args[:3])} failed with exit code {result.returncode}: {detail}")
    return result.stdout


def vault_secret(secret_id: str) -> str:
    encoded = run(
        "oci", "secrets", "secret-bundle", "get", "--auth", "resource_principal",
        "--secret-id", secret_id,
        "--query", 'data."secret-bundle-content".content', "--raw-output",
    )
    return base64.b64decode(encoded).decode()


def required(values: dict[str, Any], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Deployment parameter {name} is required")
    return value.strip()


def required_env(name: str) -> str:
    return required(dict(os.environ), name)


def env_bool(name: str) -> bool:
    value = required_env(name).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"Deployment parameter {name} must be true or false")
    return value == "true"


def optional_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    return "" if value == "not-applicable" else value


def load_resources(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"Application resource CSV was not found: {path}")
    with path.open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required_columns = {"ResourceName", "ResourceURL", "AccessMode"}
        if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
            raise ValueError("Application resource CSV must contain ResourceName, ResourceURL, and AccessMode columns")
        resources = [
            {
                "name": row["ResourceName"].strip(),
                "url": row["ResourceURL"].strip(),
                "access_mode": row["AccessMode"].strip().lower(),
            }
            for row in reader
        ]
    if not resources or any(not all(resource.values()) for resource in resources):
        raise ValueError("Application resource CSV must contain complete resource rows")
    if any(resource["access_mode"] not in {"oauth", "public"} for resource in resources):
        raise ValueError("Application resource access modes must be oauth or public")
    if any(not resource["url"].startswith("/") for resource in resources):
        raise ValueError("Application resource URLs must be relative paths beginning with /")
    return resources


def load_headers(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"Header mapping JSON was not found: {path}")
    try:
        headers = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ValueError(f"Header mapping JSON is invalid: {error}") from error
    if not isinstance(headers, list) or not headers or any(
        not isinstance(header, dict) or len(header) != 1 or not all(isinstance(key, str) and isinstance(value, str) for key, value in header.items())
        for header in headers
    ):
        raise ValueError("Header mapping JSON must be a non-empty list of single name-to-value objects")
    return headers


def load_application_properties(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError(f"Application properties file was not found: {path}")
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ValueError(f"Invalid application properties line: {line}")
        name, value = stripped.split("=", 1)
        values[name.strip()] = value.strip()
    for name in ("application_name", "application_landing_url", "application_origin_url"):
        required(values, name)
    values.setdefault("appgateway_tls_mode", "generated")
    values.setdefault("appgateway_tls_cert_secret_ocid", "")
    values.setdefault("appgateway_tls_key_secret_ocid", "")
    return values


def is_sample_configuration(source_root: Path) -> bool:
    configured = load_application_properties(source_root / "config" / "application.properties")
    defaults = load_application_properties(source_root / "defaults" / "application.properties")
    return (
        all(configured[name] == defaults[name] for name in ("application_name", "application_landing_url", "application_origin_url"))
        and filecmp.cmp(source_root / "config" / "app_resources.csv", source_root / "defaults" / "app_resources.csv", shallow=False)
        and filecmp.cmp(source_root / "config" / "header_mappings.json", source_root / "defaults" / "header_mappings.json", shallow=False)
    )


def configuration_digest(source_root: Path) -> str:
    digest = hashlib.sha256()
    for file_name in ("application.properties", "app_resources.csv", "header_mappings.json"):
        digest.update((source_root / "config" / file_name).read_bytes())
    return digest.hexdigest()


def validated_application(source_root: Path) -> tuple[dict[str, str], ParseResult, bool]:
    application = load_application_properties(source_root / "config" / "application.properties")
    landing = required(application, "application_landing_url")
    parsed_landing = urlparse(landing)
    if parsed_landing.scheme != "https" or not parsed_landing.hostname:
        raise ValueError("application_landing_url must be a complete HTTPS URL")

    origin = required(application, "application_origin_url")
    parsed_origin = urlparse(origin)
    if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.hostname:
        raise ValueError("application_origin_url must be a complete HTTP or HTTPS URL")

    smoke = is_sample_configuration(source_root)
    if not smoke:
        origin_host = parsed_origin.hostname.lower()
        try:
            is_loopback = ipaddress.ip_address(origin_host).is_loopback
        except ValueError:
            is_loopback = origin_host == "localhost" or origin_host.endswith(".localhost")
        if is_loopback:
            raise ValueError("Custom application_origin_url cannot use localhost or a loopback address")

    tls_mode = application["appgateway_tls_mode"].lower()
    if tls_mode not in {"generated", "vault"}:
        raise ValueError("appgateway_tls_mode must be generated or vault")
    if tls_mode == "vault":
        required(application, "appgateway_tls_cert_secret_ocid")
        required(application, "appgateway_tls_key_secret_ocid")

    load_resources(source_root / "config" / "app_resources.csv")
    load_headers(source_root / "config" / "header_mappings.json")
    return application, parsed_landing, smoke


def pipeline_request(source_root: Path) -> tuple[dict[str, Any], dict[str, str], bool]:
    access_mode = required_env("ACCESS_MODE")
    if access_mode not in {"Public direct", "Existing OCI Load Balancer", "External Load Balancer"}:
        raise ValueError("ACCESS_MODE must be Public direct, Existing OCI Load Balancer, or External Load Balancer")
    runtime_type = required_env("RUNTIME_TYPE")
    if runtime_type not in {"Container Instance", "Compute Instance"}:
        raise ValueError("RUNTIME_TYPE must be Container Instance or Compute Instance")
    operation = required_env("OPERATION").upper()
    if operation not in {"APPLY", "DESTROY"}:
        raise ValueError("OPERATION must be APPLY or DESTROY")
    container_size = required_env("CONTAINER_SIZE")
    if container_size not in {"Development", "Standard", "Production"}:
        raise ValueError("CONTAINER_SIZE must be Development, Standard, or Production")
    deployment_name = required_env("DEPLOYMENT_NAME")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,30}", deployment_name):
        raise ValueError("DEPLOYMENT_NAME must start with a lowercase letter and use only lowercase letters, numbers, and hyphens")

    application, parsed_landing, smoke = validated_application(source_root)
    landing = required(application, "application_landing_url")
    origin = required(application, "application_origin_url")

    cidrs = [item.strip() for item in required_env("ALLOWED_INGRESS_CIDRS_CSV").split(",") if item.strip()]
    if not cidrs:
        raise ValueError("ALLOWED_INGRESS_CIDRS_CSV must contain at least one CIDR")
    try:
        for cidr in cidrs:
            ipaddress.ip_network(cidr, strict=False)
    except ValueError as error:
        raise ValueError(f"ALLOWED_INGRESS_CIDRS_CSV contains an invalid CIDR: {error}") from error

    enable_compute_ssh = env_bool("ENABLE_COMPUTE_SSH")
    compute_ssh_public_key = optional_env("COMPUTE_SSH_PUBLIC_KEY")
    compute_ssh_allowed_cidr = optional_env("COMPUTE_SSH_ALLOWED_CIDR")

    request: dict[str, Any] = {
        "deployment_name": deployment_name,
        "region": required_env("REGION"),
        "compartment_ocid": required_env("COMPARTMENT_OCID"),
        "operation": operation,
        "target_identity_domain_url": required_env("IDENTITY_DOMAIN_URL").rstrip("/"),
        "target_iam_admin_client_id_secret_id": required_env("IAM_ADMIN_CLIENT_ID_SECRET_OCID"),
        "target_iam_admin_client_secret_id": required_env("IAM_ADMIN_CLIENT_SECRET_SECRET_OCID"),
        "deployment_vault_id": required_env("DEPLOYMENT_VAULT_ID"),
        "deployment_vault_key_id": required_env("DEPLOYMENT_VAULT_KEY_ID"),
        "ocir_pull_secret_id": required_env("OCIR_PULL_SECRET_OCID"),
        "ocir_repository_path": required_env("OCIR_REPOSITORY_PATH"),
        "ocir_image_tag": required_env("OCIR_IMAGE_TAG"),
        "application_name": required(application, "application_name"),
        "application_landing_url": landing,
        "application_origin_url": origin,
        "availability_domain": required_env("AVAILABILITY_DOMAIN"),
        "subnet_id": required_env("SUBNET_OCID"),
        "runtime_type": runtime_type,
        "compute_image_ocid": optional_env("COMPUTE_IMAGE_OCID"),
        "enable_compute_ssh": enable_compute_ssh,
        "compute_ssh_public_key": compute_ssh_public_key,
        "compute_ssh_allowed_cidr": compute_ssh_allowed_cidr,
        "assign_public_ip": env_bool("ASSIGN_PUBLIC_IP"),
        "allowed_ingress_cidrs": cidrs,
        "use_existing_oci_load_balancer": access_mode == "Existing OCI Load Balancer",
        "external_load_balancer_managed": access_mode == "External Load Balancer",
        "existing_load_balancer_id": optional_env("EXISTING_LOAD_BALANCER_ID"),
        "existing_load_balancer_backend_set_name": optional_env("EXISTING_LOAD_BALANCER_BACKEND_SET_NAME"),
        "gateway_https_port": parsed_landing.port or 443,
        "container_size": container_size,
    }
    if request["use_existing_oci_load_balancer"] and (
        not request["existing_load_balancer_id"] or not request["existing_load_balancer_backend_set_name"]
    ):
        raise ValueError("Existing OCI Load Balancer access requires its OCID and backend set name")
    if runtime_type == "Compute Instance" and not request["compute_image_ocid"]:
        raise ValueError("Compute Instance runtime requires COMPUTE_IMAGE_OCID")
    if access_mode == "Public direct" and not request["assign_public_ip"]:
        raise ValueError("Public direct access requires ASSIGN_PUBLIC_IP=true")
    if enable_compute_ssh:
        if runtime_type != "Compute Instance":
            raise ValueError("ENABLE_COMPUTE_SSH can be true only for Compute Instance")
        if not compute_ssh_public_key.startswith(("ssh-rsa ", "ssh-ed25519 ", "ecdsa-sha2-")):
            raise ValueError("COMPUTE_SSH_PUBLIC_KEY must be in OpenSSH public-key format")
        try:
            ssh_network = ipaddress.ip_network(compute_ssh_allowed_cidr, strict=False)
            if ssh_network.prefixlen == 0:
                raise ValueError("an unrestricted /0 network is not allowed")
        except ValueError as error:
            raise ValueError(f"COMPUTE_SSH_ALLOWED_CIDR must be one valid CIDR: {error}") from error
    return request, application, smoke


def extract_wallet_tool(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as outer:
            architecture = "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
            nested = next((name for name in outer.namelist() if name.startswith(f"{architecture}/") and name.endswith(".zip")), None)
            if nested:
                with zipfile.ZipFile(io.BytesIO(outer.read(nested))) as package:
                    package.extractall(destination)
                tool = next((path for path in destination.rglob("cgwallettool") if path.is_file()), None)
                if tool is not None:
                    return tool

    pending = [archive]
    extracted: set[Path] = set()
    while pending:
        package = pending.pop()
        resolved = package.resolve()
        if resolved in extracted:
            continue
        extracted.add(resolved)
        if zipfile.is_zipfile(package):
            with zipfile.ZipFile(package) as zip_package:
                zip_package.extractall(destination)
        elif tarfile.is_tarfile(package):
            with tarfile.open(package) as tar_package:
                tar_package.extractall(destination)
        else:
            continue
        tool = next((path for path in destination.rglob("cgwallettool") if path.is_file()), None)
        if tool is not None:
            return tool
        pending.extend(
            path for path in destination.rglob("*") if path.is_file() and path.resolve() not in extracted and (zipfile.is_zipfile(path) or tarfile.is_tarfile(path))
        )
    files = sorted(str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file())
    raise RuntimeError(f"Wallet-tool package does not contain cgwallettool. Extracted files: {', '.join(files[:20]) or 'no files extracted'}")


def restore_wallet_library_symlinks(tool: Path) -> None:
    library_dir = tool.parent / "lib"
    if not library_dir.is_dir():
        return
    for candidate in library_dir.iterdir():
        if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > 256:
            continue
        try:
            target_name = candidate.read_text().strip()
        except UnicodeDecodeError:
            continue
        target = candidate.parent / target_name
        if target_name and target.exists() and target_name != candidate.name:
            candidate.unlink()
            candidate.symlink_to(target_name)


def download_wallet(domain: IdentityDomain, client_id: str, client_secret: str, work: Path) -> Path:
    archive = work / "wallet-tool.zip"
    request = urllib.request.Request(domain.wallet_tool_url(), headers={"Authorization": f"Bearer {domain.token}"})
    with urllib.request.urlopen(request, timeout=120) as response:
        archive.write_bytes(response.read())
    tool = extract_wallet_tool(archive, work / "wallet-tool")
    restore_wallet_library_symlinks(tool)
    tool.chmod(0o755)
    environment = os.environ | {"LD_LIBRARY_PATH": str(tool.parent / "lib")}
    subprocess.run([str(tool), "--create", "-i", client_id], cwd=tool.parent, env=environment, input=f"{client_secret}\n", text=True, check=True)
    wallet = tool.parent / "cwallet.sso"
    if not wallet.is_file() or wallet.stat().st_size == 0:
        raise RuntimeError("Wallet tool did not create cwallet.sso")
    return wallet


def put_file_secret(request: dict[str, Any], file: Path, suffix: str) -> str:
    secret_name = f"{request['deployment_name']}-{suffix}-{os.urandom(4).hex()}"
    payload_file = file.with_suffix(f".{suffix}.secret.json")
    payload_file.write_text(json.dumps({
        "compartmentId": request["compartment_ocid"],
        "vaultId": request["deployment_vault_id"],
        "keyId": request["deployment_vault_key_id"],
        "secretName": secret_name,
        "secretContentContent": base64.b64encode(file.read_bytes()).decode(),
    }))
    try:
        response = run(
            "oci", "vault", "secret", "create-base64", "--auth", "resource_principal",
            "--from-json", f"file://{payload_file}", "--wait-for-state", "ACTIVE", "--max-wait-seconds", "300",
        )
    finally:
        payload_file.unlink(missing_ok=True)
    return json.loads(response)["data"]["id"]


def generate_tls_certificate(work: Path, hostname: str) -> tuple[Path, Path]:
    certificate = work / "cert.pem"
    key = work / "key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", str(key),
            "-out", str(certificate), "-sha256", "-days", "3650", "-nodes",
            "-subj", f"/CN={hostname}", "-addext", f"subjectAltName=DNS:{hostname}",
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return certificate, key


def validate_tls_secret_pair(certificate_text: str, key_text: str, hostname: str, work: Path) -> None:
    certificate = work / "provided-cert.pem"
    key = work / "provided-key.pem"
    certificate.write_text(certificate_text)
    key.write_text(key_text)
    key.chmod(0o600)
    try:
        run("openssl", "x509", "-in", str(certificate), "-noout", "-checkhost", hostname)
        certificate_public_key = run("openssl", "x509", "-in", str(certificate), "-pubkey", "-noout")
        private_public_key = run("openssl", "pkey", "-in", str(key), "-pubout")
        if certificate_public_key.strip() != private_public_key.strip():
            raise ValueError("Vault TLS certificate and private key do not match")
    finally:
        certificate.unlink(missing_ok=True)
        key.unlink(missing_ok=True)


def tls_secret_ids(request: dict[str, Any], application: dict[str, str], hostname: str, work: Path) -> tuple[str, str]:
    if application["appgateway_tls_mode"].lower() == "generated":
        certificate, key = generate_tls_certificate(work, hostname)
        return put_file_secret(request, certificate, "tls-cert"), put_file_secret(request, key, "tls-key")

    certificate_secret_id = required(application, "appgateway_tls_cert_secret_ocid")
    key_secret_id = required(application, "appgateway_tls_key_secret_ocid")
    validate_tls_secret_pair(vault_secret(certificate_secret_id), vault_secret(key_secret_id), hostname, work)
    return certificate_secret_id, key_secret_id


def build_smoke_image(image: str, credentials_secret_id: str, source_root: Path) -> str:
    credentials = json.loads(vault_secret(credentials_secret_id))
    registry, image_path = image.split("/", 1)
    repository, tag = image_path.rsplit(":", 1)
    smoke_image = f"{repository}-smoke:{tag}"
    run("podman", "login", registry, "--username", credentials["username"], "--password-stdin", input_text=f"{credentials['password']}\n")
    run("podman", "pull", "nginx:alpine")
    run("podman", "build", "--tag", f"{registry}/{smoke_image}", str(source_root / "smoke"))
    run("podman", "push", f"{registry}/{smoke_image}")
    return f"{registry}/{smoke_image}"


def download_object(namespace: str, bucket: str, object_name: str, destination: Path) -> bool:
    result = subprocess.run(
        ["oci", "os", "object", "get", "--auth", "resource_principal", "--namespace", namespace, "--bucket-name", bucket, "--name", object_name, "--file", str(destination)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if result.returncode:
        destination.unlink(missing_ok=True)
        detail = (result.stderr or result.stdout).strip()
        if "status\": 404" in detail or "NoSuchKey" in detail:
            return False
        raise RuntimeError(f"Unable to read runtime state object {object_name}: {detail}")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"Downloaded {object_name} is empty")
    return True


def upload_object(namespace: str, bucket: str, object_name: str, source: Path) -> None:
    run(
        "oci", "os", "object", "put", "--auth", "resource_principal", "--namespace", namespace,
        "--bucket-name", bucket, "--name", object_name, "--file", str(source), "--force",
    )


def delete_object(namespace: str, bucket: str, object_name: str) -> None:
    run(
        "oci", "os", "object", "delete", "--auth", "resource_principal", "--namespace", namespace,
        "--bucket-name", bucket, "--name", object_name, "--force",
    )


def runtime_secret_ids(state: Path) -> dict[str, str]:
    try:
        resources = json.loads(state.read_text()).get("resources", [])
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Existing runtime state could not be read") from error
    secrets: dict[str, str] = {}
    for resource in resources:
        if resource.get("mode") != "data" or resource.get("type") != "oci_secrets_secretbundle":
            continue
        name = resource.get("name")
        instances = resource.get("instances", [])
        if name in {"wallet", "tls_cert", "tls_key"} and instances:
            secret_id = instances[0].get("attributes", {}).get("secret_id")
            if isinstance(secret_id, str) and secret_id:
                secrets[name] = secret_id
    if set(secrets) != {"wallet", "tls_cert", "tls_key"}:
        raise RuntimeError("Existing runtime state does not contain the App Gateway wallet and TLS secret IDs")
    return secrets


def deployment_metadata(path: Path) -> dict[str, Any]:
    try:
        metadata = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Existing deployment metadata could not be read") from error
    if not isinstance(metadata, dict):
        raise RuntimeError("Existing deployment metadata is invalid")
    return metadata


def main() -> None:
    source_root = Path(__file__).parents[1]
    request, application, smoke = pipeline_request(source_root)
    state_bucket = required_env("STATE_BUCKET")
    namespace = run("oci", "os", "ns", "get", "--auth", "resource_principal", "--query", "data", "--raw-output").strip()
    state_object = f"state/{request['deployment_name']}/terraform.tfstate"
    metadata_object = f"state/{request['deployment_name']}/deployment.json"

    with tempfile.TemporaryDirectory(prefix="appgateway-") as temp:
        work = Path(temp)
        state = work / "terraform.tfstate"
        metadata_path = work / "deployment.json"
        runtime_state_exists = download_object(namespace, state_bucket, state_object, state)
        metadata_exists = download_object(namespace, state_bucket, metadata_object, metadata_path)
        metadata = deployment_metadata(metadata_path) if metadata_exists else {}
        current_configuration_digest = configuration_digest(source_root)

        configuration_changed = (
            request["operation"] == "APPLY"
            and runtime_state_exists
            and metadata.get("configuration_digest") not in {None, current_configuration_digest}
        )
        if configuration_changed:
            print("Application configuration changed; replacing the runtime and IAM configuration.")
            secret_ids = runtime_secret_ids(state)
            old_smoke = bool(metadata.get("sample_backend"))
            old_smoke_image = str(metadata.get("smoke_backend_image", ""))
            if old_smoke and not old_smoke_image:
                raise RuntimeError("Existing sample deployment metadata does not contain its sample image reference")
            old_values = request | {
                "appgateway_image": f"{request['region']}.ocir.io/{namespace}/{request['ocir_repository_path']}:{request['ocir_image_tag']}",
                "smoke_backend_image": old_smoke_image,
                "deploy_smoke_backend": old_smoke,
                "wallet_secret_id": secret_ids["wallet"],
                "tls_cert_secret_id": secret_ids["tls_cert"],
                "tls_key_secret_id": secret_ids["tls_key"],
            }
            (work / "runtime.tfvars.json").write_text(json.dumps(old_values))
            runtime = source_root / "runtime"
            run("terraform", "-chdir=" + str(runtime), "init", "-backend=false", "-input=false")
            run(
                "terraform", "-chdir=" + str(runtime), "destroy", "-auto-approve", "-input=false",
                f"-state={state}", f"-var-file={work / 'runtime.tfvars.json'}",
            )
            if metadata.get("iam"):
                admin_id = vault_secret(required(request, "target_iam_admin_client_id_secret_id"))
                admin_secret = vault_secret(required(request, "target_iam_admin_client_secret_id"))
                domain = IdentityDomain(required(request, "target_identity_domain_url"), admin_id, admin_secret)
                domain.delete_gateway_and_application(metadata["iam"]["gateway_id"], metadata["iam"]["application_id"])
            delete_object(namespace, state_bucket, state_object)
            if metadata_exists:
                delete_object(namespace, state_bucket, metadata_object)
            runtime_state_exists = False
            metadata_exists = False
            metadata = {}

        if request["operation"] == "DESTROY" and not runtime_state_exists:
            print("No Terraform state exists for this deployment. Nothing was destroyed.")
            return

        update_runtime = request["operation"] == "APPLY" and runtime_state_exists
        domain: IdentityDomain | None = None
        app_id = ""
        gateway_id = ""
        try:
            image = f"{request['region']}.ocir.io/{namespace}/{request['ocir_repository_path']}:{request['ocir_image_tag']}"
            if update_runtime or request["operation"] == "DESTROY":
                secret_ids = runtime_secret_ids(state)
                wallet_secret_id = secret_ids["wallet"]
                tls_cert_secret_id = secret_ids["tls_cert"]
                tls_key_secret_id = secret_ids["tls_key"]
                smoke_image = str(metadata.get("smoke_backend_image", ""))
                if smoke and not smoke_image and request["operation"] == "APPLY":
                    smoke_image = build_smoke_image(image, request["ocir_pull_secret_id"], source_root)
            else:
                print("Deployment mode detected: SAMPLE HEADER APPLICATION" if smoke else "Deployment mode detected: CUSTOM APPLICATION. Sample backend will not be deployed.")
                admin_id = vault_secret(required(request, "target_iam_admin_client_id_secret_id"))
                admin_secret = vault_secret(required(request, "target_iam_admin_client_secret_id"))
                domain = IdentityDomain(required(request, "target_identity_domain_url"), admin_id, admin_secret)
                hostname = urlparse(application["application_landing_url"]).hostname
                if hostname is None:
                    raise ValueError("application_landing_url does not include a hostname")
                resources = load_resources(source_root / "config" / "app_resources.csv")
                headers = load_headers(source_root / "config" / "header_mappings.json")
                app_id, gateway_app_name = domain.create_application(application["application_name"], application["application_landing_url"], resources, headers)
                gateway_id, gateway_client_id, gateway_client_secret = domain.create_gateway(
                    request["deployment_name"], hostname, request["gateway_https_port"], app_id, gateway_app_name, application["application_origin_url"],
                )
                wallet_secret_id = put_file_secret(request, download_wallet(domain, gateway_client_id, gateway_client_secret, work), "wallet")
                tls_cert_secret_id, tls_key_secret_id = tls_secret_ids(request, application, hostname, work)
                smoke_image = build_smoke_image(image, request["ocir_pull_secret_id"], source_root) if smoke else ""

            values = request | {
                "appgateway_image": image,
                "smoke_backend_image": smoke_image,
                "deploy_smoke_backend": bool(metadata.get("sample_backend")) if (update_runtime or request["operation"] == "DESTROY") else smoke,
                "wallet_secret_id": wallet_secret_id,
                "tls_cert_secret_id": tls_cert_secret_id,
                "tls_key_secret_id": tls_key_secret_id,
            }
            (work / "runtime.tfvars.json").write_text(json.dumps(values))
            runtime = source_root / "runtime"
            run("terraform", "-chdir=" + str(runtime), "init", "-backend=false", "-input=false")
            command = [
                "terraform", "-chdir=" + str(runtime), "destroy" if request["operation"] == "DESTROY" else "apply",
                "-auto-approve", "-input=false", f"-state={state}", f"-var-file={work / 'runtime.tfvars.json'}",
            ]
            run(*command)

            if request["operation"] == "DESTROY":
                if metadata.get("iam"):
                    admin_id = vault_secret(required(request, "target_iam_admin_client_id_secret_id"))
                    admin_secret = vault_secret(required(request, "target_iam_admin_client_secret_id"))
                    domain = IdentityDomain(required(request, "target_identity_domain_url"), admin_id, admin_secret)
                    domain.delete_gateway_and_application(metadata["iam"]["gateway_id"], metadata["iam"]["application_id"])
                delete_object(namespace, state_bucket, state_object)
                if metadata_exists:
                    delete_object(namespace, state_bucket, metadata_object)
                print("Deployment destroyed. Generated Vault secrets remain for normal Vault retention handling.")
                return

            upload_object(namespace, state_bucket, state_object, state)
            if not update_runtime:
                metadata_path.write_text(json.dumps({
                    "schema_version": 1,
                    "iam": {"application_id": app_id, "gateway_id": gateway_id},
                    "runtime_type": request["runtime_type"],
                    "sample_backend": smoke,
                    "smoke_backend_image": smoke_image,
                    "configuration_digest": current_configuration_digest,
                }, indent=2))
                upload_object(namespace, state_bucket, metadata_object, metadata_path)
            print(json.dumps({
                "deployment_name": request["deployment_name"],
                "runtime_type": request["runtime_type"],
                "configuration": "sample" if smoke else "custom",
                "state": "applied",
            }))
        except Exception:
            if not update_runtime and request["operation"] == "APPLY" and domain and gateway_id and app_id:
                try:
                    domain.delete_gateway_and_application(gateway_id, app_id)
                except Exception as cleanup_error:
                    print(f"IAM cleanup after failed deployment also failed: {cleanup_error}", file=sys.stderr)
            raise


if __name__ == "__main__":
    try:
        main()
    except (IamError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"App Gateway deployment failed: {error}", file=sys.stderr)
        raise SystemExit(1)
