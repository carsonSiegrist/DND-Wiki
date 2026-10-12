"""Generate one-time registration invite keys.

Run ``python generate_invite.py`` for one key or pass ``--count`` to create
several. Plaintext keys are printed once and are never stored by the wiki.
"""

import argparse

from app import app
from extensions import db
from invites import generate_invite_key, hash_invite_key
import models


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate one-time Campaign Wiki registration keys."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        choices=range(1, 101),
        metavar="1-100",
        help="Number of invite keys to create (default: 1).",
    )
    return parser.parse_args()


def create_invite_keys(count):
    plaintext_keys = []
    for _ in range(count):
        invite_key = generate_invite_key()
        while models.InviteKeys.query.filter_by(
            key_hash=hash_invite_key(invite_key)
        ).first() is not None:
            invite_key = generate_invite_key()

        db.session.add(
            models.InviteKeys(key_hash=hash_invite_key(invite_key))
        )
        plaintext_keys.append(invite_key)

    db.session.commit()
    return plaintext_keys


def main():
    args = parse_args()
    with app.app_context():
        invite_keys = create_invite_keys(args.count)

    print("Generated one-time invite key(s). They will not be shown again:")
    for invite_key in invite_keys:
        print(invite_key)


if __name__ == "__main__":
    main()
