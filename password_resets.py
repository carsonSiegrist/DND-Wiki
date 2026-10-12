"""One-time password-reset token helpers."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import models
from extensions import db


DEFAULT_RESET_MINUTES = 60


def generate_reset_token():
    return secrets.token_urlsafe(32)


def hash_reset_token(reset_token):
    return hashlib.sha256(reset_token.encode("utf-8")).hexdigest()


def create_password_reset(username, valid_minutes=DEFAULT_RESET_MINUTES):
    """Create a reset token and invalidate the user's earlier unused tokens."""
    if not 5 <= valid_minutes <= 1440:
        raise ValueError("Password-reset lifetime must be 5-1440 minutes.")

    user = models.User.query.filter_by(username=username).first()
    if user is None:
        raise LookupError(f'User "{username}" was not found.')

    now = datetime.now(timezone.utc)
    models.PasswordResetTokens.query.filter_by(
        user_id=user.id,
        used_at=None,
    ).update(
        {models.PasswordResetTokens.used_at: now},
        synchronize_session=False,
    )

    reset_token = generate_reset_token()
    token_hash = hash_reset_token(reset_token)
    while models.PasswordResetTokens.query.filter_by(
        token_hash=token_hash
    ).first() is not None:
        reset_token = generate_reset_token()
        token_hash = hash_reset_token(reset_token)

    expires_at = now + timedelta(minutes=valid_minutes)
    db.session.add(
        models.PasswordResetTokens(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    db.session.commit()
    return reset_token, user, expires_at
