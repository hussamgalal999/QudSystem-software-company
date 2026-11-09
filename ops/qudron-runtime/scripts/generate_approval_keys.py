#!/usr/bin/env python3
"""Generate separate Ed25519 owner-signing and runtime-verification keys."""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def write_new(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(path, mode)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--encrypt", action="store_true",
                        help="Encrypt the owner private key with an interactive passphrase")
    args = parser.parse_args()
    private_path = args.private_key.expanduser().resolve()
    public_path = args.public_key.expanduser().resolve()
    if private_path == public_path:
        parser.error("private and public key paths must be different")
    if private_path.exists() or public_path.exists():
        parser.error("refusing to overwrite an existing key file")

    password = None
    if args.encrypt:
        first = getpass.getpass("Owner private-key passphrase: ")
        second = getpass.getpass("Repeat passphrase: ")
        if not first or first != second:
            parser.error("passphrases must be non-empty and match")
        password = first.encode("utf-8")

    private_key = Ed25519PrivateKey.generate()
    encryption = (
        serialization.BestAvailableEncryption(password)
        if password else serialization.NoEncryption()
    )
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        encryption,
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    write_new(private_path, private_pem, 0o600)
    try:
        write_new(public_path, public_pem, 0o644)
    except Exception:
        private_path.unlink(missing_ok=True)
        raise
    print(f"Owner private key created with mode 0600: {private_path}")
    print(f"Runtime public key created with mode 0644: {public_path}")
    print("Keep the private key on the owner-only issuer host; never mount it into Qudron workers or FreeLLM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
