"""TLS certificate generation and SSLContext configuration for DoormanWebServer."""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

logger = logging.getLogger(__name__)


def _detect_local_ip() -> str:
    """Determine the primary local IPv4 address for SAN inclusion."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_tls_certificate(
    cert_path: str | Path = "data/tls/cert.pem",
    key_path: str | Path = "data/tls/key.pem",
    extra_hosts: list[str] | None = None,
    validity_days: int = 3650,
) -> tuple[Path, Path]:
    """Ensure a TLS certificate and private key exist on disk, generating a self-signed pair if missing.

    Args:
        cert_path: Target path for the PEM-encoded X.509 certificate.
        key_path: Target path for the PEM-encoded private key.
        extra_hosts: Optional list of additional DNS names or IP addresses to include in SAN.
        validity_days: Validity duration in days for newly generated certificates (default: 3650).

    Returns:
        Tuple of (cert_file_path, key_file_path) as resolved Path objects.
    """
    cert_file = Path(cert_path)
    key_file = Path(key_path)

    if (
        cert_file.is_file()
        and key_file.is_file()
        and cert_file.stat().st_size > 0
        and key_file.stat().st_size > 0
    ):
        return cert_file, key_file

    cert_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Generating self-signed TLS certificate at %s (key: %s)...",
        cert_file,
        key_file,
    )

    private_key = ec.generate_private_key(ec.SECP256R1())

    hostname = socket.gethostname() or "snippen-doorman-service"
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Snippen Doorman Service"),
            x509.NameAttribute(NameOID.COMMON_NAME, "snippen-doorman-service.local"),
        ]
    )

    dns_names: set[str] = {
        "localhost",
        "snippen-doorman-service.local",
        "snippen-doorman.local",
    }
    if hostname:
        dns_names.add(hostname)
        if not hostname.endswith(".local"):
            dns_names.add(f"{hostname}.local")

    ip_addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = {
        ipaddress.ip_address("127.0.0.1"),
        ipaddress.ip_address("::1"),
    }

    local_ip = _detect_local_ip()
    try:
        ip_addresses.add(ipaddress.ip_address(local_ip))
    except ValueError:
        pass

    if extra_hosts:
        for item in extra_hosts:
            cleaned = item.strip()
            if not cleaned or cleaned == "0.0.0.0":
                continue
            try:
                ip_addresses.add(ipaddress.ip_address(cleaned))
            except ValueError:
                dns_names.add(cleaned)

    san_entries: list[x509.GeneralName] = [x509.DNSName(name) for name in sorted(dns_names)] + [
        x509.IPAddress(ip) for ip in sorted(ip_addresses, key=lambda x: (x.version, x.packed))
    ]

    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(hours=1))
        .not_valid_after(now + timedelta(days=validity_days))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)

    key_file.write_bytes(key_bytes)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass

    cert_file.write_bytes(cert_bytes)
    try:
        os.chmod(cert_file, 0o644)
    except OSError:
        pass

    return cert_file, key_file


def create_ssl_context(cert_path: str | Path, key_path: str | Path) -> ssl.SSLContext:
    """Create a hardened server-side SSLContext configured with the given certificate and key.

    Args:
        cert_path: Path to the PEM certificate file.
        key_path: Path to the PEM private key file.

    Returns:
        Configured ssl.SSLContext instance with minimum TLSv1.2.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return ctx
