# File for creating temporary test pages/users for testing.
# Call with `python db_test.py` to create test entries.
# Call with `python db_test.py --delete` to instead delete the test pages/users after testing.

import sys
from textwrap import dedent

from app import app
from extensions import db
import models


TEST_USERNAME = "testuser"
TEST_EMAIL = "testemail@test.com"
TEST_PAGE_SLUG = "test-page"


def run_test():
    existing_user = models.User.query.filter_by(
        username=TEST_USERNAME
    ).first()

    if existing_user:
        print("Test user already exists. Skipping creation.")
        return

    try:
        # Create user
        user = models.User(
            username=TEST_USERNAME,
            email=TEST_EMAIL,
        )
        user.set_password("testpassword")

        db.session.add(user)

        # Flush assigns user.id without committing the transaction.
        db.session.flush()

        # Create page
        page = models.Pages(
            title="Test Page",
            slug=TEST_PAGE_SLUG,
            page_type="recap",
            created_by=user.id,
            session_number=1,
        )

        db.session.add(page)
        db.session.flush()

        # Create revision
        page_revision = models.PageRevisions(
            page_id=page.id,
            author_id=user.id,
            body_markdown=dedent("""
                # Test Page

                ## This is a test page for the D&D Wiki application.

                This page was created for testing purposes.

                - It has a title, slug, and type.
                - It is associated with a user and a session number.

                __This is a test of the markdown rendering functionality.__

                _this is a test of the markdown rendering functionality._
            """).strip(),
            edit_summary="Initial revision.",
            revision_number=1,
        )

        db.session.add(page_revision)
        db.session.flush()

        # Associate revision with page
        page.current_revision_id = page_revision.id

        # Commit everything together.
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        print(f"Error during test setup: {e}")
        return

    print("Test pages and user created successfully.")


def delete_test():
    try:
        user = models.User.query.filter_by(
            username=TEST_USERNAME
        ).first()

        page = models.Pages.query.filter_by(
            slug=TEST_PAGE_SLUG
        ).first()

        if not user and not page:
            print("Test data does not exist. Skipping deletion.")
            return

        # Delete dependent revision first.
        if page:
            revisions = models.PageRevisions.query.filter_by(
                page_id=page.id
            ).all()

            # If the page references its current revision,
            # clear that relationship before deleting revisions.
            page.current_revision_id = None
            db.session.flush()

            for revision in revisions:
                db.session.delete(revision)

            db.session.delete(page)

        # Delete user last, since pages/revisions reference it.
        if user:
            db.session.delete(user)

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        print(f"Error deleting test data: {e}")
        return

    print("Test data deleted successfully.")


def main():
    delete = len(sys.argv) > 1 and sys.argv[1] == "--delete"

    with app.app_context():
        if delete:
            print("Deleting test data...")
            delete_test()
        else:
            print("Creating test data...")
            run_test()


if __name__ == "__main__":
    main()