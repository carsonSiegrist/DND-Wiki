"""Generate a short-lived, one-time password-reset URL for a user."""

import argparse
import os

from app import app
from password_resets import DEFAULT_RESET_MINUTES, create_password_reset


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a Campaign Wiki password-reset URL."
    )
    parser.add_argument("username", help="Username whose password may be reset")
    parser.add_argument(
        "--minutes",
        type=int,
        default=DEFAULT_RESET_MINUTES,
        choices=range(5, 1441),
        metavar="5-1440",
        help="Minutes before the link expires (default: 60).",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("WIKI_BASE_URL", "http://localhost:5000"),
        help="Public wiki URL used in the printed link.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    with app.app_context():
        try:
            reset_token, user, expires_at = create_password_reset(
                args.username,
                args.minutes,
            )
        except LookupError as error:
            raise SystemExit(str(error)) from error

    reset_url = (
        f"{args.base_url.rstrip('/')}/auth/reset-password/{reset_token}"
    )
    print(f'Generated a one-time password reset for "{user.username}".')
    print(f"It expires at {expires_at.isoformat()}.")
    print("This URL will not be shown again:")
    print(reset_url)


if __name__ == "__main__":
    main()
