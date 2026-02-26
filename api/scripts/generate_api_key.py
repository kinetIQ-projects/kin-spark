"""
Generate a Spark API key and its SHA-256 hash.

Usage:
    python3 scripts/generate_api_key.py
    python3 scripts/generate_api_key.py --prefix sk_spark_demo

Output:
    API Key (store securely, give to client): sk_spark_demo_xxxxxxxx
    Key Hash (use in DB / migrations):        <sha256 hex>
"""

import argparse
import hashlib
import secrets


def generate_api_key(prefix: str = "sk_spark") -> tuple[str, str]:
    """Generate an API key and its SHA-256 hash.

    Returns:
        (plaintext_key, sha256_hash)
    """
    token = secrets.token_urlsafe(24)
    key = f"{prefix}_{token}"
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    return key, key_hash


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Spark API key")
    parser.add_argument(
        "--prefix",
        default="sk_spark",
        help="Key prefix (default: sk_spark)",
    )
    args = parser.parse_args()

    key, key_hash = generate_api_key(prefix=args.prefix)

    print(f"\nAPI Key (store securely, give to client):\n  {key}\n")
    print(f"Key Hash (use in DB / migrations):\n  {key_hash}\n")


if __name__ == "__main__":
    main()
