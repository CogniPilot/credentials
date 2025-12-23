#!/usr/bin/env python3
"""
Bitstring Status List management for credential revocation.

Implements the W3C Bitstring Status List v1.0 specification for tracking
credential revocation status.

The status list is a compressed bitstring where each bit represents the
status of a credential at that index. When a credential is revoked, its
bit is set to 1.

Status list credential format:
{
    "@context": [...],
    "id": "https://credentials.cognipilot.org/status/revocation-list",
    "type": ["VerifiableCredential", "BitstringStatusListCredential"],
    "issuer": "did:web:credentials.cognipilot.org",
    "validFrom": "...",
    "credentialSubject": {
        "id": "https://credentials.cognipilot.org/status/revocation-list#list",
        "type": "BitstringStatusList",
        "statusPurpose": "revocation",
        "encodedList": "<base64url-encoded gzip-compressed bitstring>"
    }
}

Credential status entry format (added to each issued credential):
{
    "credentialStatus": {
        "id": "https://credentials.cognipilot.org/status/revocation-list#42",
        "type": "BitstringStatusListEntry",
        "statusPurpose": "revocation",
        "statusListIndex": "42",
        "statusListCredential": "https://credentials.cognipilot.org/status/revocation-list"
    }
}
"""

import base64
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

# Constants
STATUS_LIST_SIZE = 16384  # 16KB = 131072 bits, enough for ~131k credentials
STATUS_LIST_URL = "https://credentials.cognipilot.org/status/revocation-list"
STATUS_LIST_ID = f"{STATUS_LIST_URL}#list"

# Directory paths
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
STATUS_DIR = REPO_ROOT / 'docs' / 'status'
STATUS_REGISTRY_PATH = REPO_ROOT / 'status-registry.json'


def create_empty_bitstring(size_bytes: int = STATUS_LIST_SIZE) -> bytes:
    """Create an empty bitstring of the specified size."""
    return bytes(size_bytes)


def encode_bitstring(bitstring: bytes) -> str:
    """
    Encode a bitstring to base64url-encoded gzip-compressed format.

    Per the spec, the bitstring is gzip-compressed then base64url encoded.
    """
    compressed = gzip.compress(bitstring)
    # base64url encoding (RFC 4648 section 5)
    encoded = base64.urlsafe_b64encode(compressed).decode('ascii')
    # Remove padding
    return encoded.rstrip('=')


def decode_bitstring(encoded: str) -> bytes:
    """
    Decode a base64url-encoded gzip-compressed bitstring.
    """
    # Add padding if needed
    padding = 4 - (len(encoded) % 4)
    if padding != 4:
        encoded += '=' * padding

    compressed = base64.urlsafe_b64decode(encoded)
    return gzip.decompress(compressed)


def get_bit(bitstring: bytes, index: int) -> bool:
    """Get the value of a bit at the specified index."""
    byte_index = index // 8
    bit_offset = index % 8

    if byte_index >= len(bitstring):
        raise IndexError(f"Index {index} out of range for bitstring of {len(bitstring) * 8} bits")

    return bool(bitstring[byte_index] & (1 << (7 - bit_offset)))


def set_bit(bitstring: bytes, index: int, value: bool = True) -> bytes:
    """
    Set the value of a bit at the specified index.

    Returns a new bitstring with the bit set.
    """
    byte_index = index // 8
    bit_offset = index % 8

    if byte_index >= len(bitstring):
        raise IndexError(f"Index {index} out of range for bitstring of {len(bitstring) * 8} bits")

    # Convert to bytearray for mutation
    result = bytearray(bitstring)

    if value:
        result[byte_index] |= (1 << (7 - bit_offset))
    else:
        result[byte_index] &= ~(1 << (7 - bit_offset))

    return bytes(result)


def load_status_registry() -> dict:
    """
    Load the status registry tracking credential indices.

    Registry format:
    {
        "next_index": 0,
        "credentials": {
            "wallet-slug/achievement-id": {
                "index": 0,
                "revoked": false,
                "revoked_at": null,
                "issued_at": "2025-01-01T00:00:00Z"
            }
        }
    }
    """
    if STATUS_REGISTRY_PATH.exists():
        with open(STATUS_REGISTRY_PATH) as f:
            return json.load(f)
    return {
        "next_index": 0,
        "credentials": {}
    }


def save_status_registry(registry: dict) -> None:
    """Save the status registry to disk."""
    with open(STATUS_REGISTRY_PATH, 'w') as f:
        json.dump(registry, f, indent=2)


def allocate_status_index(credential_id: str) -> int:
    """
    Allocate a status list index for a new credential.

    Args:
        credential_id: The credential identifier (e.g., "wallet-slug/achievement-id")

    Returns:
        The allocated index
    """
    registry = load_status_registry()

    # Check if already allocated
    if credential_id in registry["credentials"]:
        return registry["credentials"][credential_id]["index"]

    # Allocate new index
    index = registry["next_index"]
    registry["credentials"][credential_id] = {
        "index": index,
        "revoked": False,
        "revoked_at": None,
        "issued_at": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    }
    registry["next_index"] = index + 1

    save_status_registry(registry)
    return index


def get_status_index(credential_id: str) -> int | None:
    """
    Get the status list index for an existing credential.

    Returns None if the credential is not in the registry.
    """
    registry = load_status_registry()
    cred_info = registry["credentials"].get(credential_id)
    return cred_info["index"] if cred_info else None


def is_revoked(credential_id: str) -> bool:
    """Check if a credential is revoked."""
    registry = load_status_registry()
    cred_info = registry["credentials"].get(credential_id)
    return cred_info["revoked"] if cred_info else False


def revoke_credential(credential_id: str) -> bool:
    """
    Mark a credential as revoked.

    Returns True if successful, False if credential not found.
    """
    registry = load_status_registry()

    if credential_id not in registry["credentials"]:
        return False

    registry["credentials"][credential_id]["revoked"] = True
    registry["credentials"][credential_id]["revoked_at"] = \
        datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    save_status_registry(registry)
    return True


def unrevoke_credential(credential_id: str) -> bool:
    """
    Remove revocation from a credential.

    Returns True if successful, False if credential not found.
    """
    registry = load_status_registry()

    if credential_id not in registry["credentials"]:
        return False

    registry["credentials"][credential_id]["revoked"] = False
    registry["credentials"][credential_id]["revoked_at"] = None

    save_status_registry(registry)
    return True


def rename_credential_in_registry(old_credential_id: str, new_credential_id: str) -> bool:
    """
    Rename a credential entry in the status registry.

    This preserves the status index and revocation state when a wallet is renamed
    or a credential is moved between wallets.

    Args:
        old_credential_id: The old identifier (e.g., "old-wallet/achievement-id")
        new_credential_id: The new identifier (e.g., "new-wallet/achievement-id")

    Returns True if successful, False if old credential not found or new already exists.
    """
    if old_credential_id == new_credential_id:
        return True  # No change needed

    registry = load_status_registry()

    if old_credential_id not in registry["credentials"]:
        return False

    if new_credential_id in registry["credentials"]:
        # New ID already exists - can't rename
        return False

    # Move the entry to the new key
    registry["credentials"][new_credential_id] = registry["credentials"].pop(old_credential_id)

    save_status_registry(registry)
    return True


def rename_wallet_in_registry(old_wallet_slug: str, new_wallet_slug: str) -> int:
    """
    Rename all credential entries for a wallet in the status registry.

    Args:
        old_wallet_slug: The old wallet slug
        new_wallet_slug: The new wallet slug

    Returns the number of entries renamed.
    """
    if old_wallet_slug == new_wallet_slug:
        return 0

    registry = load_status_registry()
    renamed_count = 0

    # Find all credentials with the old wallet slug
    old_prefix = f"{old_wallet_slug}/"
    new_prefix = f"{new_wallet_slug}/"

    # Collect keys to rename (can't modify dict while iterating)
    to_rename = []
    for credential_id in registry["credentials"]:
        if credential_id.startswith(old_prefix):
            new_id = new_prefix + credential_id[len(old_prefix):]
            to_rename.append((credential_id, new_id))

    # Rename entries
    for old_id, new_id in to_rename:
        if new_id not in registry["credentials"]:
            registry["credentials"][new_id] = registry["credentials"].pop(old_id)
            renamed_count += 1

    if renamed_count > 0:
        save_status_registry(registry)

    return renamed_count


def create_credential_status(wallet_slug: str, achievement_id: str) -> dict:
    """
    Create a credentialStatus object for a new credential.

    This allocates an index and returns the status entry to embed in the credential.
    """
    credential_id = f"{wallet_slug}/{achievement_id}"
    index = allocate_status_index(credential_id)

    return {
        "id": f"{STATUS_LIST_URL}#{index}",
        "type": "BitstringStatusListEntry",
        "statusPurpose": "revocation",
        "statusListIndex": str(index),
        "statusListCredential": STATUS_LIST_URL
    }


def generate_status_list_bitstring() -> bytes:
    """
    Generate the current status list bitstring from the registry.

    Reads the registry and sets bits for all revoked credentials.
    """
    registry = load_status_registry()
    bitstring = create_empty_bitstring()

    for cred_id, cred_info in registry["credentials"].items():
        if cred_info["revoked"]:
            bitstring = set_bit(bitstring, cred_info["index"])

    return bitstring


def create_status_list_credential(signing_key=None, verification_method=None) -> dict:
    """
    Create the status list credential.

    If signing_key is provided, the credential will be signed.
    Otherwise, returns an unsigned credential.
    """
    bitstring = generate_status_list_bitstring()
    encoded_list = encode_bitstring(bitstring)

    credential = {
        "@context": [
            "https://www.w3.org/ns/credentials/v2",
            "https://w3id.org/vc/status-list/2021/v1"
        ],
        "id": STATUS_LIST_URL,
        "type": ["VerifiableCredential", "BitstringStatusListCredential"],
        "issuer": "did:web:credentials.cognipilot.org",
        "validFrom": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "credentialSubject": {
            "id": STATUS_LIST_ID,
            "type": "BitstringStatusList",
            "statusPurpose": "revocation",
            "encodedList": encoded_list
        }
    }

    if signing_key and verification_method:
        from sign_credential import sign_credential
        credential = sign_credential(credential, signing_key, verification_method)

    return credential


def save_status_list_credential(credential: dict) -> Path:
    """
    Save the status list credential to the docs directory.

    Returns the path to the saved file.
    """
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = STATUS_DIR / 'revocation-list'

    with open(output_path, 'w') as f:
        json.dump(credential, f, indent=2)

    return output_path


def update_status_list(key_path: Path = None) -> Path:
    """
    Regenerate and save the status list credential.

    If key_path is provided, the credential will be signed.
    Returns the path to the saved file.
    """
    signing_key = None
    verification_method = None

    if key_path and key_path.exists():
        from sign_credential import load_private_key
        signing_key, verification_method = load_private_key(key_path)

    credential = create_status_list_credential(signing_key, verification_method)
    return save_status_list_credential(credential)


def verify_status(credential: dict, fetch_status_list: callable = None) -> dict:
    """
    Verify the revocation status of a credential.

    Args:
        credential: The credential to check
        fetch_status_list: Optional function to fetch the status list.
                          If not provided, uses the local registry.

    Returns:
        dict with:
            - valid: True if not revoked
            - revoked: True if revoked
            - error: Error message if verification failed
    """
    result = {
        "valid": True,
        "revoked": False,
        "error": None
    }

    # Check if credential has status
    status = credential.get("credentialStatus")
    if not status:
        # No status means no revocation checking
        return result

    # Validate status entry format
    if status.get("type") != "BitstringStatusListEntry":
        result["error"] = f"Unsupported status type: {status.get('type')}"
        result["valid"] = False
        return result

    if status.get("statusPurpose") != "revocation":
        # Not a revocation status, skip
        return result

    try:
        index = int(status.get("statusListIndex", -1))
    except (ValueError, TypeError):
        result["error"] = "Invalid statusListIndex"
        result["valid"] = False
        return result

    status_list_url = status.get("statusListCredential")

    # Try local registry first
    credential_id = credential.get("id", "").replace(
        "https://credentials.cognipilot.org/profile/", ""
    )

    if credential_id:
        registry = load_status_registry()
        cred_info = registry["credentials"].get(credential_id)

        if cred_info and cred_info.get("revoked"):
            result["valid"] = False
            result["revoked"] = True
            result["revoked_at"] = cred_info.get("revoked_at")
            return result

    # If fetch function provided, verify against the actual status list
    if fetch_status_list and status_list_url:
        try:
            status_list_cred = fetch_status_list(status_list_url)
            if status_list_cred:
                encoded_list = status_list_cred.get("credentialSubject", {}).get("encodedList")
                if encoded_list:
                    bitstring = decode_bitstring(encoded_list)
                    if get_bit(bitstring, index):
                        result["valid"] = False
                        result["revoked"] = True
        except Exception as e:
            result["error"] = f"Failed to verify status: {e}"
            # Don't mark as invalid if we can't verify - just warn

    return result


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Manage credential status list')
    parser.add_argument('--update', action='store_true', help='Update the status list credential')
    parser.add_argument('--key', '-k', type=Path, help='Path to signing key')
    parser.add_argument('--stats', action='store_true', help='Show status list statistics')
    args = parser.parse_args()

    if args.stats:
        registry = load_status_registry()
        total = len(registry["credentials"])
        revoked = sum(1 for c in registry["credentials"].values() if c["revoked"])
        print(f"Total credentials: {total}")
        print(f"Revoked: {revoked}")
        print(f"Active: {total - revoked}")
        print(f"Next index: {registry['next_index']}")

    if args.update:
        path = update_status_list(args.key)
        print(f"Status list saved to: {path}")
