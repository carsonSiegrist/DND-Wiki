import unittest

from sqlalchemy import text

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
        self.assertIn(b"Original Author", view_response.data)
        self.assertIn(b"Original Creation Date", view_response.data)
        self.assertIn(b"Last Updated Author", view_response.data)
        self.assertIn(b"Last Updated Date", view_response.data)
        self.assertIn(b"page-author", view_response.data)
        self.assertIn(b"Recap Number", view_response.data)
        self.assertIn(b"<dd>4</dd>", view_response.data)
        self.assertIn(b'href="/categories/discoveries"', view_response.data)
        self.assertIn(b'href="/categories/factions"', view_response.data)
        self.assertIn(b'href="/categories/locations"', view_response.data)
        self.assertLess(
            view_response.data.index(b">Discoveries</a>"),
            view_response.data.index(b">Factions</a>"),
        )
        self.assertLess(
            view_response.data.index(b">Factions</a>"),
            view_response.data.index(b">Locations</a>"),
        )
        self.assertIn(b'class="notification-dismiss"', view_response.data)
        self.assertIn(b"Dismiss notification", view_response.data)

        form_response = self.client.get("/pages/new")
        self.assertLess(
            form_response.data.index(b"Discoveries"),
            form_response.data.index(b"Factions"),
        )
        self.assertLess(
            form_response.data.index(b"Factions"),
            form_response.data.index(b"Locations"),
        )
        self.assertIn(b'type="checkbox"', form_response.data)
        self.assertNotIn(b'<select id="categories"', form_response.data)

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

    def test_page_can_reclaim_its_own_historical_title_when_edited(self):
        create_response = self.client.post(
            "/pages/new",
            data={
                "title": "The First Name",
                "body_markdown": "Original notes",
            },
        )
        self.assertEqual(create_response.status_code, 302)

        rename_response = self.client.post(
            "/pages/edit/the-first-name",
            data={
                "title": "The Second Name",
                "body_markdown": "Renamed notes",
                "edit_summary": "Renamed the page",
            },
        )
        self.assertEqual(rename_response.status_code, 302)
        self.assertIn("/pages/view/the-second-name", rename_response.headers["Location"])

        reclaim_response = self.client.post(
            "/pages/edit/the-second-name",
            data={
                "title": "The First Name",
                "body_markdown": "Restored-title notes",
                "edit_summary": "Restored the original title",
            },
        )
        self.assertEqual(reclaim_response.status_code, 302)
        self.assertIn("/pages/view/the-first-name", reclaim_response.headers["Location"])

        with self.app.app_context():
            page = models.Pages.query.filter_by(title="The First Name").one()
            current_revision = db.session.get(
                models.PageRevisions,
                page.current_revision_id,
            )

            self.assertEqual(page.slug, "the-first-name")
            self.assertEqual(current_revision.revision_number, 3)
            self.assertEqual(
                db.session.get(models.PageRevisionTitles, current_revision.id).title,
                "The First Name",
            )
            self.assertIsNone(
                models.PageTitleAliases.query.filter_by(
                    title="The First Name"
                ).first()
            )
            second_name_alias = models.PageTitleAliases.query.filter_by(
                title="The Second Name"
            ).one()
            self.assertEqual(second_name_alias.page_id, page.id)

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

        updated_view_response = self.client.get("/pages/view/the-renamed-road")
        self.assertIn(b"Last Updated Author", updated_view_response.data)
        self.assertIn(b"other-user", updated_view_response.data)

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
            self.assertEqual(
                db.session.get(models.PageUpdateAuthors, page.id).user_id,
                self.other_user_id,
            )
            revision_titles = {
                revision.id: db.session.get(
                    models.PageRevisionTitles,
                    revision.id,
                ).title
                for revision in revisions
            }
            self.assertEqual(revision_titles[revisions[0].id], "Old Road Name")
            self.assertEqual(revision_titles[revisions[1].id], "The Renamed Road")

        history_response = self.client.get(
            "/pages/view/the-renamed-road/versions"
        )
        self.assertEqual(history_response.status_code, 200)
        self.assertIn(b"Version 2", history_response.data)
        self.assertIn(b"(current)", history_response.data)
        self.assertIn(b"Added current travel discoveries", history_response.data)
        self.assertIn(b"Version 1", history_response.data)
        self.assertIn(b"Initial revision.", history_response.data)
        self.assertIn(b"Old Road Name", history_response.data)
        self.assertIn(b"The Renamed Road", history_response.data)
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
        self.assertTrue(
            restore_response.headers["Location"].endswith(
                "/pages/view/old-road-name"
            )
        )

        restored_page_response = self.client.get(
            "/pages/view/old-road-name"
        )
        self.assertIn(b"Original road notes", restored_page_response.data)
        self.assertIn(b'<h1 class="title">Old Road Name</h1>', restored_page_response.data)

        with self.app.app_context():
            page = models.Pages.query.filter_by(title="Old Road Name").one()
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
            "/pages/view/old-road-name/versions/2"
        )
        self.assertIn(b"Delete Revision", old_revision_response.data)
        self.assertNotIn(b"Delete Page", old_revision_response.data)
        self.assertEqual(
            self.client.post(
                "/pages/view/old-road-name/versions/1/delete"
            ).status_code,
            400,
        )

        delete_revision_response = self.client.post(
            "/pages/view/old-road-name/versions/2/delete"
        )
        self.assertEqual(delete_revision_response.status_code, 302)

        with self.app.app_context():
            page = models.Pages.query.filter_by(title="Old Road Name").one()
            remaining_revisions = models.PageRevisions.query.filter_by(
                page_id=page.id
            ).all()
            self.assertEqual(len(remaining_revisions), 1)
            self.assertEqual(remaining_revisions[0].revision_number, 1)
            self.assertIsNotNone(
                db.session.get(
                    models.PageRevisionTitles,
                    remaining_revisions[0].id,
                )
            )

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
            target_id = target.id

            self.assertEqual(len(links), 2)
            self.assertEqual(links_by_title["Target Page"].target_page_id, target.id)
            self.assertIsNone(links_by_title["Missing Page"].target_page_id)

        rendered_response = self.client.get("/pages/view/source-page")
        self.assertIn(
            (
                f'class="wiki-hyperlink" href="/pages/id/{target_id}">'
                "Target Page</a>"
            ).encode(),
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
            self.assertEqual(target_link.target_page_id, target_id)

        stable_link_response = self.client.get(f"/pages/id/{target_id}")
        self.assertEqual(stable_link_response.status_code, 302)
        self.assertTrue(
            stable_link_response.headers["Location"].endswith(
                "/pages/view/renamed-target"
            )
        )

        renamed_render_response = self.client.get("/pages/view/source-page")
        self.assertIn(
            (
                f'class="wiki-hyperlink" href="/pages/id/{target_id}">'
                "Target Page</a>"
            ).encode(),
            renamed_render_response.data,
        )

        alias_edit_response = self.client.post(
            "/pages/edit/source-page",
            data={
                "title": "Source Page",
                "body_markdown": (
                    "Old label [[Target Page]] and current label "
                    "[[Renamed Target]]."
                ),
                "edit_summary": "Used both target titles",
            },
        )
        self.assertEqual(alias_edit_response.status_code, 302)

        with self.app.app_context():
            source = models.Pages.query.filter_by(title="Source Page").one()
            links = models.PageLinks.query.filter_by(source_page_id=source.id).all()
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0].target_page_id, target_id)

        both_labels_response = self.client.get("/pages/view/source-page")
        stable_href = f'href="/pages/id/{target_id}"'.encode()
        self.assertEqual(both_labels_response.data.count(stable_href), 2)
        self.assertIn(b">Target Page</a>", both_labels_response.data)
        self.assertIn(b">Renamed Target</a>", both_labels_response.data)

        replacement_response = self.client.post(
            "/pages/new",
            data={
                "title": "Target Page",
                "body_markdown": "Replacement target",
            },
        )
        self.assertEqual(replacement_response.status_code, 200)
        self.assertIn(
            b"That title was previously used by a wiki page and is reserved",
            replacement_response.data,
        )

        with self.app.app_context():
            self.assertIsNone(
                models.Pages.query.filter_by(title="Target Page").first()
            )

        self.login_as(self.admin_id)
        delete_response = self.client.post("/pages/delete/renamed-target")
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            source = models.Pages.query.filter_by(title="Source Page").one()
            target_link = models.PageLinks.query.filter_by(
                source_page_id=source.id,
                target_title="Target Page",
            ).one()
            self.assertIsNone(target_link.target_page_id)
            aliases = models.PageTitleAliases.query.filter(
                models.PageTitleAliases.title.in_(
                    {"Target Page", "Renamed Target"}
                )
            ).all()
            self.assertEqual(
                {alias.title for alias in aliases},
                {"Target Page", "Renamed Target"},
            )
            self.assertTrue(all(alias.page_id is None for alias in aliases))

        unresolved_response = self.client.get("/pages/view/source-page")
        self.assertIn(
            b'class="unresolved-hyperlink" href="/pages/new?title=Target+Page">Target Page</a>',
            unresolved_response.data,
        )

    def test_pages_use_shared_navigation_and_stylesheet(self):
        authenticated_response = self.client.get("/pages/new")

        self.assertIn(b'href="/">Home</a>', authenticated_response.data)
        self.assertIn(b'href="/pages">All Pages</a>', authenticated_response.data)
        self.assertIn(b'href="/categories">Categories</a>', authenticated_response.data)
        self.assertIn(b'action="/search"', authenticated_response.data)
        self.assertIn(b'name="q"', authenticated_response.data)
        self.assertIn(b'class="user-navigation"', authenticated_response.data)
        self.assertIn(b"page-author", authenticated_response.data)
        self.assertIn(b'action="/auth/logout"', authenticated_response.data)
        self.assertIn(b">Log Out</button>", authenticated_response.data)
        self.assertIn(b'href="/static/style.css"', authenticated_response.data)

        with self.client.session_transaction() as session:
            session.clear()

        for path, heading in (
            ("/", b"Welcome to the Wiki"),
            ("/auth/login", b"Log In"),
            ("/auth/register", b"Create Account"),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(heading, response.data)
            self.assertIn(b'href="/">Home</a>', response.data)
            self.assertIn(b'href="/pages">All Pages</a>', response.data)
            self.assertIn(b'href="/categories">Categories</a>', response.data)
            self.assertIn(b'href="/auth/login">Log In</a>', response.data)
            self.assertIn(b'href="/auth/register">Register</a>', response.data)
            self.assertNotIn(b">Log Out</button>", response.data)
            self.assertIn(b'href="/static/style.css"', response.data)

    def test_all_pages_and_category_indexes(self):
        article_response = self.client.post(
            "/pages/new",
            data={
                "title": "Zulu Article",
                "categories": [str(self.category_id)],
                "new_categories-0": "Zebra",
                "new_categories-1": "Alpha",
                "body_markdown": "Article body",
            },
        )
        self.assertEqual(article_response.status_code, 302)

        earlier_article_response = self.client.post(
            "/pages/new",
            data={
                "title": "Able Article",
                "body_markdown": "Earlier alphabetical article",
            },
        )
        self.assertEqual(earlier_article_response.status_code, 302)

        recap_response = self.client.post(
            "/pages/new",
            data={
                "title": "A Later Recap",
                "is_recap": "y",
                "session_number": "5",
                "categories": [str(self.category_id)],
                "body_markdown": "Recap body",
            },
        )
        self.assertEqual(recap_response.status_code, 302)

        all_pages_response = self.client.get("/pages")
        self.assertEqual(all_pages_response.status_code, 200)
        self.assertIn(b"Recap Number", all_pages_response.data)
        self.assertIn(b"Articles", all_pages_response.data)
        self.assertLess(
            all_pages_response.data.index(b"An Earlier Adventure"),
            all_pages_response.data.index(b"A Later Recap"),
        )
        self.assertLess(
            all_pages_response.data.index(b"Able Article"),
            all_pages_response.data.index(b"Zulu Article"),
        )
        self.assertIn(b'class="category-list"', all_pages_response.data)

        categories_response = self.client.get("/categories")
        self.assertEqual(categories_response.status_code, 200)
        self.assertLess(
            categories_response.data.index(b">Alpha</a>"),
            categories_response.data.index(b">Locations</a>"),
        )
        self.assertLess(
            categories_response.data.index(b">Locations</a>"),
            categories_response.data.index(b">Zebra</a>"),
        )
        self.assertIn(b'<a href="/categories/locations">Locations</a>', categories_response.data)
        self.assertIn(b"<td>2</td>", categories_response.data)

        category_response = self.client.get("/categories/locations")
        self.assertEqual(category_response.status_code, 200)
        self.assertLess(
            category_response.data.index(b"A Later Recap"),
            category_response.data.index(b"Zulu Article"),
        )
        self.assertIn(
            b'<strong><a href="/categories/locations">Locations</a></strong>',
            category_response.data,
        )
        self.assertLess(
            category_response.data.index(b">Locations</a>"),
            category_response.data.index(b">Alpha</a>"),
        )
        self.assertLess(
            category_response.data.index(b">Alpha</a>"),
            category_response.data.index(b">Zebra</a>"),
        )

    def test_homepage_shows_most_wanted_and_ten_recent_revisions(self):
        page_data = [
            (
                "Wanted Source One",
                "[[Missing Temple]] [[Other Mystery]] [[Missing Temple]] "
                "[[Existing Topic]]",
            ),
            (
                "Wanted Source Two",
                "[[Missing Temple]] [[Existing Topic]]",
            ),
            ("Existing Topic", "This page resolves its incoming links."),
        ]
        page_data.extend(
            (f"Activity Page {number}", f"Activity body {number}")
            for number in range(1, 9)
        )

        for title, body_markdown in page_data:
            response = self.client.post(
                "/pages/new",
                data={
                    "title": title,
                    "body_markdown": body_markdown,
                },
            )
            self.assertEqual(response.status_code, 302)

        self.login_as(self.other_user_id)
        edit_response = self.client.post(
            "/pages/edit/wanted-source-one",
            data={
                "title": "Wanted Source One",
                "body_markdown": page_data[0][1],
                "edit_summary": "Clarified the missing leads",
            },
        )
        self.assertEqual(edit_response.status_code, 302)

        home_response = self.client.get("/")
        self.assertEqual(home_response.status_code, 200)
        compact_home = " ".join(home_response.get_data(as_text=True).split())

        self.assertIn("Most Wanted", compact_home)
        self.assertIn(
            '<td>2</td> <td><a href="/pages/new?title=Missing+Temple">'
            "Missing Temple</a></td>",
            compact_home,
        )
        self.assertIn(
            '<td>1</td> <td><a href="/pages/new?title=Other+Mystery">'
            "Other Mystery</a></td>",
            compact_home,
        )
        self.assertLess(
            compact_home.index(">Missing Temple</a>"),
            compact_home.index(">Other Mystery</a>"),
        )
        self.assertNotIn("/pages/new?title=Existing+Topic", compact_home)

        self.assertIn("Recent Activity", compact_home)
        self.assertEqual(
            home_response.data.count(b'class="recent-revision-row"'),
            10,
        )
        self.assertIn(
            '<a href="/pages/view/wanted-source-one">Wanted Source One</a> '
            "</td> <td>Clarified the missing leads</td>",
            compact_home,
        )
        self.assertIn("<td>other-user</td>", compact_home)

        create_wanted_response = self.client.post(
            "/pages/new",
            data={
                "title": "Missing Temple",
                "body_markdown": "The wanted page now exists.",
            },
        )
        self.assertEqual(create_wanted_response.status_code, 302)

        resolved_home_response = self.client.get("/")
        self.assertNotIn(
            b'/pages/new?title=Missing+Temple',
            resolved_home_response.data,
        )

    def test_search_prefers_titles_and_highlights_the_first_content_match(self):
        title_match_response = self.client.post(
            "/pages/new",
            data={
                "title": "Red Wizard",
                "body_markdown": "The opening overview of this mysterious person.",
            },
        )
        self.assertEqual(title_match_response.status_code, 302)

        content_match_response = self.client.post(
            "/pages/new",
            data={
                "title": "Yellow Wizard",
                "body_markdown": (
                    "A harmless beginning that eventually reveals she fears the "
                    "Red Wizard greatly. A later Red Wizard reference follows. "
                    "<script>alert('danger')</script>"
                ),
            },
        )
        self.assertEqual(content_match_response.status_code, 302)

        response = self.client.get("/search?q=Red+Wizard")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"2 results for", response.data)
        self.assertLess(
            response.data.index(b'href="/pages/view/red-wizard"'),
            response.data.index(b'href="/pages/view/yellow-wizard"'),
        )
        self.assertIn(b"The opening overview of this mysterious person.", response.data)
        self.assertEqual(response.data.count(b"<mark>Red Wizard</mark>"), 1)
        self.assertNotIn(b"<script>alert('danger')</script>", response.data)
        self.assertNotIn(b"danger", response.data)

    def test_search_index_tracks_edits_restores_and_deletion(self):
        create_response = self.client.post(
            "/pages/new",
            data={
                "title": "First Search Name",
                "body_markdown": "The ancient lantern is hidden here.",
            },
        )
        self.assertEqual(create_response.status_code, 302)

        edit_response = self.client.post(
            "/pages/edit/first-search-name",
            data={
                "title": "Second Search Name",
                "body_markdown": "The silver compass replaced the earlier clue.",
                "edit_summary": "Changed the clue",
            },
        )
        self.assertEqual(edit_response.status_code, 302)

        old_content_response = self.client.get("/search?q=ancient+lantern")
        self.assertIn(b"0 results for", old_content_response.data)
        self.assertNotIn(
            b'href="/pages/view/second-search-name"',
            old_content_response.data,
        )

        updated_response = self.client.get("/search?q=silver+compass")
        self.assertIn(b'href="/pages/view/second-search-name"', updated_response.data)

        restore_response = self.client.post(
            "/pages/view/second-search-name/versions/1/restore"
        )
        self.assertEqual(restore_response.status_code, 302)

        restored_response = self.client.get("/search?q=ancient+lantern")
        self.assertIn(b'href="/pages/view/first-search-name"', restored_response.data)
        removed_content_response = self.client.get("/search?q=silver+compass")
        self.assertIn(b"0 results for", removed_content_response.data)

        self.login_as(self.admin_id)
        delete_response = self.client.post("/pages/delete/first-search-name")
        self.assertEqual(delete_response.status_code, 302)

        deleted_response = self.client.get("/search?q=ancient+lantern")
        self.assertIn(b"0 results for", deleted_response.data)
        self.assertNotIn(
            b'href="/pages/view/first-search-name"',
            deleted_response.data,
        )

    def test_search_index_can_be_rebuilt(self):
        create_response = self.client.post(
            "/pages/new",
            data={
                "title": "Rebuildable Page",
                "body_markdown": "A phoenix keyword lives here.",
            },
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db.session.execute(text("DELETE FROM page_search"))
            db.session.commit()

        missing_response = self.client.get("/search?q=phoenix")
        self.assertIn(b"0 results for", missing_response.data)

        command_response = self.app.test_cli_runner().invoke(
            args=["rebuild-search-index"]
        )
        self.assertEqual(command_response.exit_code, 0)
        self.assertIn("Indexed 1 pages.", command_response.output)

        rebuilt_response = self.client.get("/search?q=phoenix")
        self.assertIn(b'href="/pages/view/rebuildable-page"', rebuilt_response.data)


if __name__ == "__main__":
    unittest.main()
