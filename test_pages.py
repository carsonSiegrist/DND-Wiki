import unittest

from app import create_app
from extensions import db
from manage_user_role import update_user_role
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

            other_user = models.User(
                username="other-user",
                email="other@example.com",
            )
            other_user.set_password("test-password")
            db.session.add(other_user)

            admin = models.User(
                username="wiki-admin",
                email="admin@example.com",
                role="admin",
            )
            admin.set_password("test-password")
            db.session.add(admin)
            db.session.flush()
            self.other_user_id = other_user.id
            self.admin_id = admin.id

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

        self.login_as(self.user_id)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session.clear()
            session["_user_id"] = str(user_id)
            session["_fresh"] = True

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
                "new_categories-0": "Discoveries",
                "new_categories-1": "Factions",
                "body_markdown": "# A dangerous expedition",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.headers["Location"].endswith(
                "/pages/view/into-the-sunken-temple?saved=1&draft=create"
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
            self.assertEqual(
                category_names,
                {"Locations", "Discoveries", "Factions"},
            )

        view_response = self.client.get(response.headers["Location"])
        self.assertEqual(view_response.status_code, 200)
        self.assertIn(b'<h1 class="title">Into the Sunken Temple</h1>', view_response.data)
        self.assertIn(b"<h1>A dangerous expedition</h1>", view_response.data)
        self.assertIn(b"View Page History", view_response.data)
        self.assertIn(b"localStorage.removeItem", view_response.data)
        self.assertIn(b'href="/static/style.css"', view_response.data)

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

    def test_another_user_can_edit_article_and_a_new_revision_is_created(self):
        create_response = self.client.post(
            "/pages/new",
            data={
                "title": "Old Road Name",
                "categories": [str(self.category_id)],
                "body_markdown": "Original road notes",
            },
        )
        self.assertEqual(create_response.status_code, 302)

        self.login_as(self.other_user_id)
        edit_form_response = self.client.get("/pages/edit/old-road-name")
        self.assertIn(b"Edit Summary", edit_form_response.data)

        edit_response = self.client.post(
            "/pages/edit/old-road-name",
            data={
                "title": "The Renamed Road",
                "is_recap": "y",
                "session_number": "4",
                "new_categories-0": "Travel",
                "body_markdown": "Updated by another player",
                "edit_summary": "Added current travel discoveries",
            },
        )

        self.assertEqual(edit_response.status_code, 302)
        self.assertIn("/pages/view/the-renamed-road", edit_response.headers["Location"])

        with self.app.app_context():
            page = models.Pages.query.filter_by(title="The Renamed Road").one()
            revisions = models.PageRevisions.query.filter_by(page_id=page.id).order_by(
                models.PageRevisions.revision_number
            ).all()
            category_names = {
                category.name
                for category in models.Categories.query.join(
                    models.PageCategories,
                    models.Categories.id == models.PageCategories.category_id,
                ).filter(models.PageCategories.page_id == page.id)
            }

            self.assertEqual(page.page_type, "recap")
            self.assertEqual(page.session_number, 4)
            self.assertEqual(len(revisions), 2)
            self.assertEqual(revisions[0].body_markdown, "Original road notes")
            self.assertEqual(revisions[1].body_markdown, "Updated by another player")
            self.assertEqual(
                revisions[1].edit_summary,
                "Added current travel discoveries",
            )
            self.assertEqual(revisions[1].author_id, self.other_user_id)
            self.assertEqual(page.current_revision_id, revisions[1].id)
            self.assertEqual(category_names, {"Travel"})

        history_response = self.client.get(
            "/pages/view/the-renamed-road/versions"
        )
        self.assertEqual(history_response.status_code, 200)
        self.assertIn(b"Version 2", history_response.data)
        self.assertIn(b"(current)", history_response.data)
        self.assertIn(b"Added current travel discoveries", history_response.data)
        self.assertIn(b"Version 1", history_response.data)
        self.assertIn(b"Initial revision.", history_response.data)
        self.assertIn(b"other-user", history_response.data)
        self.assertIn(b"page-author", history_response.data)

        current_revision_response = self.client.get(
            "/pages/view/the-renamed-road/versions/2"
        )
        self.assertEqual(current_revision_response.status_code, 302)
        self.assertTrue(
            current_revision_response.headers["Location"].endswith(
                "/pages/view/the-renamed-road"
            )
        )

        old_revision_response = self.client.get(
            "/pages/view/the-renamed-road/versions/1"
        )
        self.assertEqual(old_revision_response.status_code, 200)
        self.assertIn(b"Viewing version 1", old_revision_response.data)
        self.assertIn(b"Original road notes", old_revision_response.data)
        self.assertIn(b"Restore Version", old_revision_response.data)
        self.assertNotIn(b"Edit Page", old_revision_response.data)
        self.assertNotIn(b"Delete Revision", old_revision_response.data)
        self.assertEqual(
            self.client.post(
                "/pages/view/the-renamed-road/versions/1/delete"
            ).status_code,
            403,
        )

        restore_response = self.client.post(
            "/pages/view/the-renamed-road/versions/1/restore"
        )
        self.assertEqual(restore_response.status_code, 302)

        restored_page_response = self.client.get(
            "/pages/view/the-renamed-road"
        )
        self.assertIn(b"Original road notes", restored_page_response.data)

        with self.app.app_context():
            page = models.Pages.query.filter_by(title="The Renamed Road").one()
            restored_revision = db.session.get(
                models.PageRevisions,
                page.current_revision_id,
            )
            self.assertEqual(restored_revision.revision_number, 1)
            self.assertEqual(
                models.PageRevisions.query.filter_by(page_id=page.id).count(),
                2,
            )

        self.login_as(self.admin_id)
        old_revision_response = self.client.get(
            "/pages/view/the-renamed-road/versions/2"
        )
        self.assertIn(b"Delete Revision", old_revision_response.data)
        self.assertNotIn(b"Delete Page", old_revision_response.data)
        self.assertEqual(
            self.client.post(
                "/pages/view/the-renamed-road/versions/1/delete"
            ).status_code,
            400,
        )

        delete_revision_response = self.client.post(
            "/pages/view/the-renamed-road/versions/2/delete"
        )
        self.assertEqual(delete_revision_response.status_code, 302)

        with self.app.app_context():
            page = models.Pages.query.filter_by(title="The Renamed Road").one()
            remaining_revisions = models.PageRevisions.query.filter_by(
                page_id=page.id
            ).all()
            self.assertEqual(len(remaining_revisions), 1)
            self.assertEqual(remaining_revisions[0].revision_number, 1)

    def test_regular_user_cannot_create_or_edit_official_pages(self):
        forged_response = self.client.post(
            "/pages/new",
            data={
                "title": "Forged Official Page",
                "page_type": "official",
                "body_markdown": "Not actually official",
            },
        )
        self.assertEqual(forged_response.status_code, 302)

        with self.app.app_context():
            forged_page = models.Pages.query.filter_by(
                title="Forged Official Page"
            ).one()
            self.assertEqual(forged_page.page_type, "article")

        self.login_as(self.admin_id)
        official_response = self.client.post(
            "/pages/new",
            data={
                "title": "Campaign Rules",
                "page_type": "official",
                "body_markdown": "Official rules",
            },
        )
        self.assertEqual(official_response.status_code, 302)

        self.login_as(self.user_id)
        view_response = self.client.get("/pages/view/campaign-rules")
        self.assertEqual(view_response.status_code, 200)
        self.assertNotIn(b"Edit Page", view_response.data)
        self.assertNotIn(b"Delete Page", view_response.data)
        self.assertEqual(self.client.get("/pages/edit/campaign-rules").status_code, 403)
        self.assertEqual(self.client.post("/pages/delete/campaign-rules").status_code, 403)

    def test_admin_can_create_edit_and_delete_official_page(self):
        self.login_as(self.admin_id)

        form_response = self.client.get("/pages/new")
        self.assertIn(b"Page Type", form_response.data)
        self.assertIn(b'value="official"', form_response.data)

        create_response = self.client.post(
            "/pages/new",
            data={
                "title": "Official Lore",
                "page_type": "official",
                "body_markdown": "First official version",
            },
        )
        self.assertEqual(create_response.status_code, 302)

        edit_form_response = self.client.get("/pages/edit/official-lore")
        self.assertIn(b"Page Type", edit_form_response.data)
        self.assertIn(b'selected value="official"', edit_form_response.data)

        edit_response = self.client.post(
            "/pages/edit/official-lore",
            data={
                "title": "Official Lore",
                "page_type": "official",
                "body_markdown": "Second official version",
            },
        )
        self.assertEqual(edit_response.status_code, 302)

        view_response = self.client.get("/pages/view/official-lore")
        self.assertIn(b"Edit Page", view_response.data)
        self.assertIn(b"Delete Page", view_response.data)
        self.assertIn(b"<strong>Official Lore</strong>", view_response.data)
        self.assertIn(b"This action cannot be undone.", view_response.data)

        with self.app.app_context():
            page = models.Pages.query.filter_by(title="Official Lore").one()
            page_id = page.id
            self.assertEqual(page.page_type, "official")
            self.assertEqual(
                models.PageRevisions.query.filter_by(page_id=page.id).count(),
                2,
            )

        delete_response = self.client.post("/pages/delete/official-lore")
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            self.assertIsNone(db.session.get(models.Pages, page_id))
            self.assertEqual(
                models.PageRevisions.query.filter_by(page_id=page_id).count(),
                0,
            )

    def test_regular_user_cannot_delete_own_page(self):
        create_response = self.client.post(
            "/pages/new",
            data={
                "title": "User Owned Page",
                "body_markdown": "Must survive",
            },
        )
        self.assertEqual(create_response.status_code, 302)
        self.assertEqual(self.client.post("/pages/delete/user-owned-page").status_code, 403)

        with self.app.app_context():
            self.assertIsNotNone(
                models.Pages.query.filter_by(title="User Owned Page").first()
            )

    def test_role_management_function_promotes_and_demotes_user(self):
        with self.app.app_context():
            user, old_role = update_user_role("page-author", "admin")
            self.assertEqual(old_role, "user")
            self.assertEqual(user.role, "admin")

            user, old_role = update_user_role("page-author", "user")
            self.assertEqual(old_role, "admin")
            self.assertEqual(user.role, "user")

    def test_wiki_links_render_and_stay_synchronized(self):
        target_response = self.client.post(
            "/pages/new",
            data={
                "title": "Target Page",
                "body_markdown": "Target body",
            },
        )
        self.assertEqual(target_response.status_code, 302)

        source_response = self.client.post(
            "/pages/new",
            data={
                "title": "Source Page",
                "body_markdown": (
                    "See [[  Target Page  ]] and [[Target Page]] plus "
                    "[[ Missing Page ]]."
                ),
            },
        )
        self.assertEqual(source_response.status_code, 302)

        with self.app.app_context():
            source = models.Pages.query.filter_by(title="Source Page").one()
            target = models.Pages.query.filter_by(title="Target Page").one()
            links = models.PageLinks.query.filter_by(source_page_id=source.id).all()
            links_by_title = {link.target_title: link for link in links}

            self.assertEqual(len(links), 2)
            self.assertEqual(links_by_title["Target Page"].target_page_id, target.id)
            self.assertIsNone(links_by_title["Missing Page"].target_page_id)

        rendered_response = self.client.get("/pages/view/source-page")
        self.assertIn(
            b'class="wiki-hyperlink" href="/pages/view/target-page">Target Page</a>',
            rendered_response.data,
        )
        self.assertIn(
            b'class="unresolved-hyperlink" href="/pages/new?title=Missing+Page">Missing Page</a>',
            rendered_response.data,
        )
        self.assertNotIn(b"[[Target Page]]", rendered_response.data)

        edit_form_response = self.client.get("/pages/edit/source-page")
        self.assertIn(b"[[  Target Page  ]]", edit_form_response.data)
        self.assertIn(b"[[ Missing Page ]]", edit_form_response.data)

        prefilled_response = self.client.get("/pages/new?title=Missing+Page")
        self.assertIn(b'value="Missing Page"', prefilled_response.data)
        self.assertIn(b"const preservePrefilledTitle = true", prefilled_response.data)

        missing_response = self.client.post(
            "/pages/new",
            data={
                "title": "Missing Page",
                "body_markdown": "Now this page exists",
            },
        )
        self.assertEqual(missing_response.status_code, 302)

        with self.app.app_context():
            source = models.Pages.query.filter_by(title="Source Page").one()
            missing = models.Pages.query.filter_by(title="Missing Page").one()
            missing_link = models.PageLinks.query.filter_by(
                source_page_id=source.id,
                target_title="Missing Page",
            ).one()
            self.assertEqual(missing_link.target_page_id, missing.id)

        edit_response = self.client.post(
            "/pages/edit/source-page",
            data={
                "title": "Source Page",
                "body_markdown": "Only [[ Another Missing ]] remains.",
                "edit_summary": "Changed links",
            },
        )
        self.assertEqual(edit_response.status_code, 302)

        with self.app.app_context():
            source = models.Pages.query.filter_by(title="Source Page").one()
            links = models.PageLinks.query.filter_by(source_page_id=source.id).all()
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0].target_title, "Another Missing")
            self.assertIsNone(links[0].target_page_id)

        restore_response = self.client.post(
            "/pages/view/source-page/versions/1/restore"
        )
        self.assertEqual(restore_response.status_code, 302)

        with self.app.app_context():
            source = models.Pages.query.filter_by(title="Source Page").one()
            links = models.PageLinks.query.filter_by(source_page_id=source.id).all()
            links_by_title = {link.target_title: link for link in links}
            self.assertEqual(set(links_by_title), {"Target Page", "Missing Page"})
            self.assertIsNotNone(links_by_title["Target Page"].target_page_id)
            self.assertIsNotNone(links_by_title["Missing Page"].target_page_id)

        rename_response = self.client.post(
            "/pages/edit/target-page",
            data={
                "title": "Renamed Target",
                "body_markdown": "Target body",
                "edit_summary": "Renamed page",
            },
        )
        self.assertEqual(rename_response.status_code, 302)

        with self.app.app_context():
            source = models.Pages.query.filter_by(title="Source Page").one()
            target_link = models.PageLinks.query.filter_by(
                source_page_id=source.id,
                target_title="Target Page",
            ).one()
            self.assertIsNone(target_link.target_page_id)

        replacement_response = self.client.post(
            "/pages/new",
            data={
                "title": "Target Page",
                "body_markdown": "Replacement target",
            },
        )
        self.assertEqual(replacement_response.status_code, 302)

        self.login_as(self.admin_id)
        delete_response = self.client.post("/pages/delete/target-page")
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            source = models.Pages.query.filter_by(title="Source Page").one()
            target_link = models.PageLinks.query.filter_by(
                source_page_id=source.id,
                target_title="Target Page",
            ).one()
            self.assertIsNone(target_link.target_page_id)

        unresolved_response = self.client.get("/pages/view/source-page")
        self.assertIn(
            b'class="unresolved-hyperlink" href="/pages/new?title=Target+Page">Target Page</a>',
            unresolved_response.data,
        )

    def test_pages_use_shared_navigation_and_stylesheet(self):
        authenticated_response = self.client.get("/pages/new")

        self.assertIn(b'href="/">Home</a>', authenticated_response.data)
        self.assertIn(b"page-author", authenticated_response.data)
        self.assertIn(b'href="/static/style.css"', authenticated_response.data)

        with self.client.session_transaction() as session:
            session.clear()

        for path, heading in (
            ("/", b"Welcome to the D&amp;D Wiki!"),
            ("/auth/login", b"Log In"),
            ("/auth/register", b"Create Account"),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(heading, response.data)
            self.assertIn(b'href="/">Home</a>', response.data)
            self.assertIn(b'href="/auth/login">Log In</a>', response.data)
            self.assertIn(b'href="/auth/register">Register</a>', response.data)
            self.assertIn(b'href="/static/style.css"', response.data)


if __name__ == "__main__":
    unittest.main()
