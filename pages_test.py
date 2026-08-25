# File for creating temporary test pages/users for testing.
# Call with `python db_test.py` to create test entries.
# Call with `python db_test.py --delete` to instead delete the test pages/users after testing.

import sys
from app import app, db
import models
from textwrap import dedent



# Minimal test requires a user, a page, and a revision.
def run_test():
    if user := models.User.query.filter_by(username="testuser").first():
        print("Test user already exists. Skipping creation.")
        return

    try:
        #Create user
        user = models.User(
            username="testuser",
            email="testemail@test.com",
        )

        user.set_password("testpassword")

        db.session.add(user)
        db.session.commit()

        # Create page
        page = models.Pages(
            title="Test Page",
            slug="test-page",
            page_type="recap",
            created_by=user.id,
            session_number=1
        )
        db.session.add(page)
        db.session.commit()

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
            revision_number=1
        )
        db.session.add(page_revision)
        db.session.commit()

        #Associate revision with page
        page.current_revision_id = page_revision.id
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        print(f"Error during test setup: {e}")
        return

    else:
        print("Test pages and user created successfully.")


def delete_test():
    if not (user := models.User.query.filter_by(username="testuser").first()):
        print("Test user does not exist. Skipping deletion.")
        return

    #Delete the test user, page, and revision created by run_test()
    try:
        user = models.User.query.filter_by(username="testuser").first()
        if user:
            db.session.delete(user)
            db.session.commit()
        
        page = models.Pages.query.filter_by(slug="test-page").first()
        if page:
            page_revision = models.PageRevisions.query.filter_by(page_id=page.id).first()
            if page_revision:
                db.session.delete(page_revision)
            db.session.delete(page)
            db.session.commit()

    except Exception as e:
        db.session.rollback()
        print(f"Error deleting test data: {e}")
    
    else:
        print("Test data deleted successfully.")

def main():
    delete = False
    if len(sys.argv) > 1 and sys.argv[1] == "--delete":
        delete = True

    with app.app_context():
        if delete:
            print("Deleting test data...")
            delete_test()
        else:
            print("Creating test data...")
            run_test()


if __name__ == "__main__":
    main()