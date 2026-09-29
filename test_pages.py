import unittest

from app import create_app
from extensions import db
import models


class PageCreationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            user = models.User(
                username="page-author",
                email="author@example.com",
            )
            user.set_password("test-password")
            db.session.add(user)
            db.session.flush()
            self.user_id = user.id

            category = models.Categories(
                name="Locations",
                slug="locations",
                created_by=user.id,
            )
            db.session.add(category)
            db.session.flush()
            self.category_id = category.id

            recap = models.Pages(
                title="An Earlier Adventure",
                slug="an-earlier-adventure",
                page_type="recap",
                created_by=user.id,
                session_number=3,
            )
            db.session.add(recap)
            db.session.commit()

        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.user_id)
            session["_fresh"] = True

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()

    def test_form_defaults_to_next_session_and_has_draft_support(self):
        response = self.client.get("/pages/new")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="4"', response.data)
        self.assertIn(b"New Category", response.data)
        self.assertIn(b"localStorage.setItem", response.data)

    def test_create_recap_with_existing_and_new_categories(self):
        response = self.client.post(
            "/pages/new",
            data={
                "title": "Into the Sunken Temple",
                "is_recap": "y",
                "session_number": "4",
                "categories": [str(self.category_id)],
                "new_category": "Discoveries",
                "body_markdown": "# A dangerous expedition",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.headers["Location"].endswith(
                "/pages/view/into-the-sunken-temple?created=1"
            )
        )

        with self.app.app_context():
            page = models.Pages.query.filter_by(
                title="Into the Sunken Temple"
            ).one()
            revision = db.session.get(models.PageRevisions, page.current_revision_id)
            category_names = {
                category.name
                for category in models.Categories.query.join(
                    models.PageCategories,
                    models.Categories.id == models.PageCategories.category_id,
                ).filter(models.PageCategories.page_id == page.id)
            }

            self.assertEqual(page.page_type, "recap")
            self.assertEqual(page.session_number, 4)
            self.assertEqual(revision.revision_number, 1)
            self.assertEqual(revision.body_markdown, "# A dangerous expedition")
            self.assertEqual(category_names, {"Locations", "Discoveries"})

        view_response = self.client.get(response.headers["Location"])
        self.assertEqual(view_response.status_code, 200)
        self.assertIn(b"<h1>A dangerous expedition</h1>", view_response.data)
        self.assertIn(b"localStorage.removeItem", view_response.data)

    def test_recap_requires_a_session_number(self):
        response = self.client.post(
            "/pages/new",
            data={
                "title": "Missing Session",
                "is_recap": "y",
                "session_number": "",
                "body_markdown": "Body",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Recaps require a session number!", response.data)

        with self.app.app_context():
            self.assertIsNone(
                models.Pages.query.filter_by(title="Missing Session").first()
            )

    def test_article_does_not_store_a_session_number(self):
        response = self.client.post(
            "/pages/new",
            data={
                "title": "The Northern Road",
                "session_number": "0",
                "body_markdown": "Road notes",
            },
        )

        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            page = models.Pages.query.filter_by(title="The Northern Road").one()
            self.assertEqual(page.page_type, "article")
            self.assertIsNone(page.session_number)


if __name__ == "__main__":
    unittest.main()
