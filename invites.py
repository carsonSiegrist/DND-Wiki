"""Invite-key generation and hashing helpers."""

import hashlib
import secrets


def generate_invite_key():
    """Return a cryptographically random invite key suitable for sharing once."""
    return secrets.token_urlsafe(24)


def hash_invite_key(invite_key):
    """Return the irreversible value stored in the database."""
    return hashlib.sha256(invite_key.strip().encode("utf-8")).hexdigest()
