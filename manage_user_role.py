import argparse

from app import app
from extensions import db
import models


VALID_ROLES = ("user", "admin")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Update a Campaign Wiki user's role."
    )
    parser.add_argument("username", help="Username to update")
    parser.add_argument("role", choices=VALID_ROLES, help="Role to assign")
    return parser.parse_args()


def update_user_role(username, role):
    if role not in VALID_ROLES:
        raise ValueError(f'Invalid role "{role}".')

    user = models.User.query.filter_by(username=username).first()
    if user is None:
        raise LookupError(f'User "{username}" was not found.')

    old_role = user.role
    user.role = role
    db.session.commit()
    return user, old_role


def main():
    args = parse_args()

    with app.app_context():
        try:
            user, old_role = update_user_role(args.username, args.role)
        except LookupError as error:
            raise SystemExit(str(error)) from error
        print(f'Updated "{user.username}" from {old_role} to {user.role}.')


if __name__ == "__main__":
    main()
