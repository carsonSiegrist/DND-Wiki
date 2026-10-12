import io
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from PIL import Image
from sqlalchemy import text

from app import create_app
from extensions import db
from generate_invite import create_invite_keys
from invites import hash_invite_key
from manage_user_role import update_user_role
import models
from password_resets import create_password_reset, hash_reset_token


class PageCreationTestCase(unittest.TestCase):
    def setUp(self):
        self.upload_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "WTF_CSRF_ENABLED": False,
                "RATELIMIT_ENABLED": False,
                "IMAGE_UPLOAD_ROOT": self.upload_directory.name,
            }
        )
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            from search import initialize_search_index

            initialize_search_index()

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
        self.upload_directory.cleanup()

    def login_as(self, user_id):
        with self.app.app_context():
            session_identity = db.session.get(models.User, user_id).get_id()
        with self.client.session_transaction() as session:
            session.clear()
            session["_user_id"] = session_identity
            session["_fresh"] = True

    def make_image_upload(self, size=(64, 48), image_format="PNG"):
        image_data = io.BytesIO()
        image = Image.new("RGB", size, color=(120, 40, 180))
        image.save(image_data, format=image_format)
        image.close()
        image_data.seek(0)
        return image_data

    def upload_image(
        self,
        upload_session,
        filename="campaign-map.png",
        size=(64, 48),
        page_id=None,
    ):
        data = {
            "upload_session": upload_session,
            "images": (self.make_image_upload(size=size), filename),
        }
        if page_id is not None:
            data["page_id"] = str(page_id)
        return self.client.post(
            "/images/upload",
            data=data,
            content_type="multipart/form-data",
        )

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
        self.assertIn(
            b'<h1 class="title">Into the Sunken Temple -- Session 4 Recap</h1>',
            view_response.data,
        )
        self.assertIn(b"<h1>A dangerous expedition</h1>", view_response.data)
        self.assertIn(b"View Page History", view_response.data)
        self.assertIn(b"localStorage.removeItem", view_response.data)
        self.assertIn(b'href="/static/style.css"', view_response.data)
        self.assertIn(b"Original Author", view_response.data)
        self.assertIn(b"Original Creation Date", view_response.data)
        self.assertIn(b"Last Updated Author", view_response.data)
        self.assertIn(b"Last Updated Date", view_response.data)
        self.assertIn(b"page-author", view_response.data)
        self.assertIn(b'<p class="page-metadata">', view_response.data)
        self.assertNotIn(b'<dl class="page-metadata">', view_response.data)
        self.assertNotIn(b"Recap Number", view_response.data)
        self.assertIn(b'action="/pages/edit/into-the-sunken-temple"', view_response.data)
        self.assertIn(b">Edit Page</button>", view_response.data)
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
            self.assertEqual(revisions[0].page_type, "article")
            self.assertIsNone(revisions[0].session_number)
            self.assertEqual(revisions[1].page_type, "recap")
            self.assertEqual(revisions[1].session_number, 4)
            revision_categories = {
                revision.id: {
                    snapshot.category_name
                    for snapshot in models.PageRevisionCategories.query.filter_by(
                        revision_id=revision.id
                    )
                }
                for revision in revisions
            }
            self.assertEqual(revision_categories[revisions[0].id], {"Locations"})
            self.assertEqual(revision_categories[revisions[1].id], {"Travel"})
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
        self.assertNotIn(b"Session 4 Recap", old_revision_response.data)
        self.assertIn(b">Locations</a>", old_revision_response.data)
        self.assertNotIn(b">Travel</a>", old_revision_response.data)
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
        self.assertIn(b">Locations</a>", restored_page_response.data)
        self.assertNotIn(b">Travel</a>", restored_page_response.data)

        with self.app.app_context():
            page = models.Pages.query.filter_by(title="Old Road Name").one()
            restored_revision = db.session.get(
                models.PageRevisions,
                page.current_revision_id,
            )
            self.assertEqual(restored_revision.revision_number, 1)
            self.assertEqual(page.page_type, "article")
            self.assertIsNone(page.session_number)
            restored_category_names = {
                category.name
                for category in models.Categories.query.join(
                    models.PageCategories,
                    models.Categories.id == models.PageCategories.category_id,
                ).filter(models.PageCategories.page_id == page.id)
            }
            self.assertEqual(restored_category_names, {"Locations"})
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

    def test_regular_user_cannot_restore_an_old_official_snapshot(self):
        self.login_as(self.admin_id)
        create_response = self.client.post(
            "/pages/new",
            data={
                "title": "Changing Policy",
                "page_type": "official",
                "body_markdown": "The original official policy.",
            },
        )
        self.assertEqual(create_response.status_code, 302)
        edit_response = self.client.post(
            "/pages/edit/changing-policy",
            data={
                "title": "Changing Policy",
                "page_type": "article",
                "body_markdown": "This is now a community article.",
                "edit_summary": "Changed this to an article",
            },
        )
        self.assertEqual(edit_response.status_code, 302)

        self.login_as(self.user_id)
        old_revision_response = self.client.get(
            "/pages/view/changing-policy/versions/1"
        )
        self.assertEqual(old_revision_response.status_code, 200)
        self.assertNotIn(b"Restore Version", old_revision_response.data)
        restore_response = self.client.post(
            "/pages/view/changing-policy/versions/1/restore"
        )
        self.assertEqual(restore_response.status_code, 403)

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
            self.assertEqual(aliases, [])

        unresolved_response = self.client.get("/pages/view/source-page")
        self.assertIn(
            b'class="unresolved-hyperlink" href="/pages/new?title=Target+Page">Target Page</a>',
            unresolved_response.data,
        )

        self.login_as(self.user_id)
        recreated_historical_title = self.client.post(
            "/pages/new",
            data={
                "title": "Target Page",
                "body_markdown": "Recreated from the historical title.",
            },
        )
        self.assertEqual(recreated_historical_title.status_code, 302)

        recreated_current_title = self.client.post(
            "/pages/new",
            data={
                "title": "Renamed Target",
                "body_markdown": "Recreated from the title at deletion.",
            },
        )
        self.assertEqual(recreated_current_title.status_code, 302)

        with self.app.app_context():
            recreated_titles = {
                page.title
                for page in models.Pages.query.filter(
                    models.Pages.title.in_({"Target Page", "Renamed Target"})
                )
            }
            self.assertEqual(
                recreated_titles,
                {"Target Page", "Renamed Target"},
            )

    def test_pages_use_shared_navigation_and_stylesheet(self):
        authenticated_response = self.client.get("/pages/new")

        self.assertIn(b'href="/">Home</a>', authenticated_response.data)
        self.assertIn(b'href="/pages">All Pages</a>', authenticated_response.data)
        self.assertIn(b'href="/categories">Categories</a>', authenticated_response.data)
        self.assertIn(b'action="/pages/new"', authenticated_response.data)
        self.assertIn(b">Create Page</button>", authenticated_response.data)
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
            self.assertNotIn(b">Create Page</button>", response.data)
            self.assertIn(b'href="/auth/login">Log In</a>', response.data)
            self.assertIn(b'href="/auth/register">Register</a>', response.data)
            self.assertNotIn(b">Log Out</button>", response.data)
            self.assertIn(b'href="/static/style.css"', response.data)

    def test_registration_requires_and_consumes_a_one_time_invite_key(self):
        invite_key = "test-invite-key-that-is-long-enough"
        with self.app.app_context():
            invite = models.InviteKeys(key_hash=hash_invite_key(invite_key))
            db.session.add(invite)
            db.session.commit()
            invite_id = invite.id

        with self.client.session_transaction() as session:
            session.clear()

        invalid_response = self.client.post(
            "/auth/register",
            data={
                "invite_key": "invalid-invite-key",
                "username": "invited-user",
                "email": "invited@example.com",
                "password": "long-test-password",
                "password_check": "long-test-password",
            },
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertIn(b"invalid or has already been used", invalid_response.data)

        register_response = self.client.post(
            "/auth/register",
            data={
                "invite_key": invite_key,
                "username": "invited-user",
                "email": "invited@example.com",
                "password": "long-test-password",
                "password_check": "long-test-password",
            },
        )
        self.assertEqual(register_response.status_code, 302)
        self.assertTrue(register_response.headers["Location"].endswith("/auth/login"))

        reused_response = self.client.post(
            "/auth/register",
            data={
                "invite_key": invite_key,
                "username": "second-invited-user",
                "email": "second-invited@example.com",
                "password": "long-test-password",
                "password_check": "long-test-password",
            },
        )
        self.assertEqual(reused_response.status_code, 200)
        self.assertIn(b"invalid or has already been used", reused_response.data)

        with self.app.app_context():
            invite = db.session.get(models.InviteKeys, invite_id)
            invited_user = models.User.query.filter_by(
                username="invited-user"
            ).one()
            self.assertIsNotNone(invite.used_at)
            self.assertEqual(invite.used_by, invited_user.id)
            self.assertIsNone(
                models.User.query.filter_by(username="second-invited-user").first()
            )

    def test_invite_generator_stores_only_hashes(self):
        with self.app.app_context():
            invite_keys = create_invite_keys(2)
            stored_hashes = {
                invite.key_hash for invite in models.InviteKeys.query.all()
            }

        self.assertEqual(len(invite_keys), 2)
        self.assertEqual(len(set(invite_keys)), 2)
        self.assertEqual(
            stored_hashes,
            {hash_invite_key(invite_key) for invite_key in invite_keys},
        )
        self.assertTrue(all(key not in stored_hashes for key in invite_keys))

    def test_password_reset_is_one_time_and_revokes_existing_sessions(self):
        with self.app.app_context():
            first_token, first_username, _ = create_password_reset(
                "page-author", 60
            )
            reset_token, reset_username, _ = create_password_reset(
                "page-author", 60
            )
            first_record = models.PasswordResetTokens.query.filter_by(
                token_hash=hash_reset_token(first_token)
            ).one()
            self.assertIsNotNone(first_record.used_at)
            self.assertNotEqual(first_token, reset_token)
            self.assertNotIn(
                reset_token,
                {
                    record.token_hash
                    for record in models.PasswordResetTokens.query.all()
                },
            )

        # The command prints this after its application context has closed, so
        # it must be a plain value rather than a detached SQLAlchemy model.
        self.assertEqual(first_username, "page-author")
        self.assertEqual(reset_username, "page-author")

        reset_client = self.app.test_client()
        form_response = reset_client.get(
            f"/auth/reset-password/{reset_token}"
        )
        self.assertEqual(form_response.status_code, 200)
        self.assertIn(b"Choose a new password", form_response.data)
        self.assertEqual(form_response.headers["Cache-Control"], "no-store")
        self.assertEqual(form_response.headers["Referrer-Policy"], "no-referrer")

        reset_response = reset_client.post(
            f"/auth/reset-password/{reset_token}",
            data={
                "password": "brand-new-password",
                "password_check": "brand-new-password",
            },
        )
        self.assertEqual(reset_response.status_code, 302)
        self.assertTrue(reset_response.headers["Location"].endswith("/auth/login"))

        with self.app.app_context():
            user = db.session.get(models.User, self.user_id)
            reset_record = models.PasswordResetTokens.query.filter_by(
                token_hash=hash_reset_token(reset_token)
            ).one()
            self.assertTrue(user.check_password("brand-new-password"))
            self.assertFalse(user.check_password("test-password"))
            self.assertEqual(user.session_version, 1)
            self.assertIsNotNone(reset_record.used_at)

        revoked_session_response = self.client.get("/pages/new")
        self.assertEqual(revoked_session_response.status_code, 302)
        self.assertIn("/auth/login", revoked_session_response.headers["Location"])

        old_password_response = reset_client.post(
            "/auth/login",
            data={"username": "page-author", "password": "test-password"},
        )
        self.assertEqual(old_password_response.status_code, 200)
        self.assertIn(b"Invalid username or password", old_password_response.data)
        new_password_response = reset_client.post(
            "/auth/login",
            data={
                "username": "page-author",
                "password": "brand-new-password",
            },
        )
        self.assertEqual(new_password_response.status_code, 302)
        self.assertEqual(reset_client.get("/pages/new").status_code, 200)

        reused_response = reset_client.get(
            f"/auth/reset-password/{reset_token}"
        )
        self.assertEqual(reused_response.status_code, 200)
        self.assertIn(b"invalid, expired, or has already been used", reused_response.data)

    def test_expired_password_reset_is_rejected(self):
        expired_token = "expired-reset-token"
        with self.app.app_context():
            db.session.add(
                models.PasswordResetTokens(
                    user_id=self.user_id,
                    token_hash=hash_reset_token(expired_token),
                    expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                )
            )
            db.session.commit()

        response = self.client.get(f"/auth/reset-password/{expired_token}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"invalid, expired, or has already been used", response.data)
        self.assertNotIn(b"Set New Password", response.data)

    def test_required_configuration_is_validated(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "SECRET_KEY, SQLALCHEMY_DATABASE_URI",
        ):
            create_app(
                {
                    "SECRET_KEY": None,
                    "SQLALCHEMY_DATABASE_URI": None,
                }
            )

    def test_login_is_rate_limited(self):
        limited_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "rate-limit-test-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "WTF_CSRF_ENABLED": False,
                "RATELIMIT_ENABLED": True,
                "IMAGE_UPLOAD_ROOT": self.upload_directory.name,
            }
        )
        with limited_app.app_context():
            db.create_all()
            from search import initialize_search_index

            initialize_search_index()

        client = limited_app.test_client()
        for _ in range(10):
            response = client.post(
                "/auth/login",
                data={"username": "missing", "password": "incorrect"},
            )
            self.assertEqual(response.status_code, 200)

        limited_response = client.post(
            "/auth/login",
            data={"username": "missing", "password": "incorrect"},
        )
        self.assertEqual(limited_response.status_code, 429)

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

        self.login_as(self.admin_id)
        official_response = self.client.post(
            "/pages/new",
            data={
                "title": "Campaign Rules",
                "page_type": "official",
                "body_markdown": "The official campaign rules.",
            },
        )
        self.assertEqual(official_response.status_code, 302)
        self.login_as(self.user_id)

        all_pages_response = self.client.get("/pages")
        self.assertEqual(all_pages_response.status_code, 200)
        self.assertIn(b"Official Pages", all_pages_response.data)
        self.assertIn(b"Recap Number", all_pages_response.data)
        self.assertIn(b"Articles", all_pages_response.data)
        official_section_start = all_pages_response.data.index(
            b'id="official-pages"'
        )
        recap_section_start = all_pages_response.data.index(b'id="recap-pages"')
        article_section_start = all_pages_response.data.index(
            b'id="article-pages"'
        )
        self.assertLess(official_section_start, recap_section_start)
        self.assertLess(recap_section_start, article_section_start)
        self.assertIn(
            b"Campaign Rules",
            all_pages_response.data[official_section_start:recap_section_start],
        )
        self.assertNotIn(
            b"Campaign Rules",
            all_pages_response.data[article_section_start:],
        )
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
        self.assertNotIn(b"Manage Category", category_response.data)

    def test_only_admin_can_rename_and_delete_categories(self):
        create_response = self.client.post(
            "/pages/new",
            data={
                "title": "Categorized Page",
                "categories": [str(self.category_id)],
                "body_markdown": "This page belongs to a category.",
            },
        )
        self.assertEqual(create_response.status_code, 302)
        edit_response = self.client.post(
            "/pages/edit/categorized-page",
            data={
                "title": "Categorized Page",
                "categories": [str(self.category_id)],
                "body_markdown": "A second version of the categorized page.",
                "edit_summary": "Added a second version",
            },
        )
        self.assertEqual(edit_response.status_code, 302)

        rename_response = self.client.post(
            "/categories/locations/rename",
            data={"name": "Places and Regions"},
        )
        self.assertEqual(rename_response.status_code, 403)
        delete_response = self.client.post("/categories/locations/delete")
        self.assertEqual(delete_response.status_code, 403)

        self.login_as(self.admin_id)
        manage_response = self.client.get("/categories/locations")
        self.assertIn(b"Manage Category", manage_response.data)
        self.assertIn(b'action="/categories/locations/rename"', manage_response.data)
        self.assertIn(b'action="/categories/locations/delete"', manage_response.data)

        rename_response = self.client.post(
            "/categories/locations/rename",
            data={"name": "Places and Regions"},
        )
        self.assertEqual(rename_response.status_code, 302)
        self.assertTrue(
            rename_response.headers["Location"].endswith(
                "/categories/places-and-regions"
            )
        )
        self.assertEqual(self.client.get("/categories/locations").status_code, 404)
        renamed_response = self.client.get("/categories/places-and-regions")
        self.assertEqual(renamed_response.status_code, 200)
        self.assertIn(b"Categorized Page", renamed_response.data)

        with self.app.app_context():
            renamed_category = models.Categories.query.filter_by(
                slug="places-and-regions"
            ).one()
            renamed_category_id = renamed_category.id
            page = models.Pages.query.filter_by(title="Categorized Page").one()
            self.assertIsNotNone(
                models.PageCategories.query.filter_by(
                    page_id=page.id,
                    category_id=renamed_category_id,
                ).first()
            )

        delete_response = self.client.post(
            "/categories/places-and-regions/delete"
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertTrue(delete_response.headers["Location"].endswith("/categories"))

        with self.app.app_context():
            self.assertIsNone(db.session.get(models.Categories, renamed_category_id))
            self.assertEqual(
                models.PageCategories.query.filter_by(
                    category_id=renamed_category_id
                ).count(),
                0,
            )
            self.assertIsNotNone(
                models.Pages.query.filter_by(title="Categorized Page").first()
            )

        page_response = self.client.get("/pages/view/categorized-page")
        self.assertEqual(page_response.status_code, 200)
        historical_response = self.client.get(
            "/pages/view/categorized-page/versions/1"
        )
        self.assertEqual(historical_response.status_code, 200)
        self.assertIn(b"Locations", historical_response.data)
        self.assertNotIn(b'href="/categories/locations"', historical_response.data)
        self.assertNotIn(
            b'href="/categories/places-and-regions"',
            historical_response.data,
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

    def test_search_prefers_titles_and_highlights_the_best_content_match(self):
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
                    "Red paint marks an unimportant door near the entrance. "
                    "A harmless beginning eventually reveals she fears the "
                    "Red archmage known as the Wizard greatly. "
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
        self.assertIn(
            b"<mark>Red archmage known as the Wizard</mark>",
            response.data,
        )
        self.assertNotIn(b"<mark>Red</mark> paint", response.data)
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

    def test_multiple_images_are_processed_attached_and_publicly_rendered(self):
        upload_session = str(uuid4())
        upload_response = self.client.post(
            "/images/upload",
            data={
                "upload_session": upload_session,
                "images": [
                    (self.make_image_upload(size=(7000, 100)), "wide-map.png"),
                    (self.make_image_upload(size=(320, 240)), "portrait.png"),
                ],
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(upload_response.status_code, 201)
        uploaded_images = upload_response.get_json()["images"]
        self.assertEqual(len(uploaded_images), 2)

        first_image = uploaded_images[0]
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(
            self.client.get(first_image["thumbnail_url"]).status_code,
            403,
        )

        self.login_as(self.user_id)
        image_markdown = "\n\n".join((
            (
                f"[![Image 1]({uploaded_images[0]['display_url']})]"
                f"({uploaded_images[0]['master_url']})"
            ),
            (
                f'<img src="{uploaded_images[1]["display_url"]}" '
                'alt="Image 2">'
            ),
        ))
        create_response = self.client.post(
            "/pages/new",
            data={
                "image_upload_session": upload_session,
                "title": "Illustrated Expedition",
                "body_markdown": image_markdown,
            },
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            from image_service import get_variant_path

            page = models.Pages.query.filter_by(
                title="Illustrated Expedition"
            ).one()
            assets = models.ImageAssets.query.filter_by(page_id=page.id).all()
            revision_images = models.RevisionImages.query.filter_by(
                revision_id=page.current_revision_id
            ).all()
            self.assertEqual(len(assets), 2)
            self.assertEqual(len(revision_images), 2)

            wide_asset = db.session.get(models.ImageAssets, first_image["id"])
            expected_maximums = {
                "master": 6000,
                "display": 2000,
                "thumbnail": 320,
            }
            for variant, maximum_dimension in expected_maximums.items():
                variant_path = get_variant_path(wide_asset, variant)
                self.assertTrue(variant_path.is_file())
                with Image.open(variant_path) as stored_image:
                    self.assertLessEqual(max(stored_image.size), maximum_dimension)
                    self.assertEqual(stored_image.format, "WEBP")

        with self.client.session_transaction() as session:
            session.clear()
        view_response = self.client.get("/pages/view/illustrated-expedition")
        self.assertEqual(view_response.status_code, 200)
        self.assertIn(first_image["display_url"].encode(), view_response.data)
        self.assertIn(first_image["master_url"].encode(), view_response.data)
        self.assertIn(b'loading="lazy"', view_response.data)
        self.assertIn(b'decoding="async"', view_response.data)
        image_response = self.client.get(first_image["display_url"])
        self.assertEqual(image_response.status_code, 200)
        self.assertIn("public", image_response.headers["Cache-Control"])
        self.assertIn("immutable", image_response.headers["Cache-Control"])
        image_response.close()
        self.assertEqual(
            self.client.get(f"/images/{first_image['id']}/unknown").status_code,
            404,
        )

    def test_images_remain_with_history_and_restore_with_old_revision(self):
        upload_session = str(uuid4())
        uploaded_image = self.upload_image(upload_session).get_json()["images"][0]
        image_markdown = (
            f"[![Campaign map]({uploaded_image['display_url']})]"
            f"({uploaded_image['master_url']})"
        )
        create_response = self.client.post(
            "/pages/new",
            data={
                "image_upload_session": upload_session,
                "title": "Changing Map",
                "body_markdown": image_markdown,
            },
        )
        self.assertEqual(create_response.status_code, 302)

        edit_response = self.client.post(
            "/pages/edit/changing-map",
            data={
                "image_upload_session": str(uuid4()),
                "title": "Changing Map",
                "body_markdown": "The current revision has no map.",
                "edit_summary": "Removed the outdated map",
            },
        )
        self.assertEqual(edit_response.status_code, 302)

        with self.app.app_context():
            page = models.Pages.query.filter_by(title="Changing Map").one()
            revisions = models.PageRevisions.query.filter_by(
                page_id=page.id
            ).order_by(models.PageRevisions.revision_number).all()
            self.assertEqual(
                models.RevisionImages.query.filter_by(
                    revision_id=revisions[0].id
                ).count(),
                1,
            )
            self.assertEqual(
                models.RevisionImages.query.filter_by(
                    revision_id=revisions[1].id
                ).count(),
                0,
            )

        with self.client.session_transaction() as session:
            session.clear()
        old_revision_response = self.client.get(
            "/pages/view/changing-map/versions/1"
        )
        self.assertIn(uploaded_image["display_url"].encode(), old_revision_response.data)
        image_response = self.client.get(uploaded_image["display_url"])
        self.assertEqual(image_response.status_code, 200)
        image_response.close()

        self.login_as(self.other_user_id)
        restore_response = self.client.post(
            "/pages/view/changing-map/versions/1/restore"
        )
        self.assertEqual(restore_response.status_code, 302)
        restored_response = self.client.get("/pages/view/changing-map")
        self.assertIn(uploaded_image["display_url"].encode(), restored_response.data)

        cross_page_response = self.client.post(
            "/pages/new",
            data={
                "image_upload_session": str(uuid4()),
                "title": "Improper Image Reuse",
                "body_markdown": image_markdown,
            },
        )
        self.assertEqual(cross_page_response.status_code, 200)
        self.assertIn(b"another page cannot be attached", cross_page_response.data)

        code_example_response = self.client.post(
            "/pages/new",
            data={
                "image_upload_session": str(uuid4()),
                "title": "Image Syntax Notes",
                "body_markdown": f"`{uploaded_image['display_url']}`",
            },
        )
        self.assertEqual(code_example_response.status_code, 302)

        with self.app.app_context():
            from image_service import get_asset_directory

            image_directory = get_asset_directory(uploaded_image["id"])
            self.assertTrue(image_directory.is_dir())

        self.login_as(self.admin_id)
        delete_response = self.client.post("/pages/delete/changing-map")
        self.assertEqual(delete_response.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(
                db.session.get(models.ImageAssets, uploaded_image["id"])
            )
            self.assertFalse(image_directory.exists())

    def test_invalid_images_and_unsafe_markdown_are_rejected(self):
        invalid_response = self.client.post(
            "/images/upload",
            data={
                "upload_session": str(uuid4()),
                "images": (io.BytesIO(b"not actually an image"), "fake.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid_response.status_code, 400)

        svg_response = self.client.post(
            "/images/upload",
            data={
                "upload_session": str(uuid4()),
                "images": (
                    io.BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'),
                    "disguised.png",
                ),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(svg_response.status_code, 400)

        create_response = self.client.post(
            "/pages/new",
            data={
                "title": "Sanitized Page",
                "body_markdown": (
                    "**Safe text**\n\n"
                    "<script>alert('unsafe')</script>\n\n"
                    '<img src="https://example.com/tracker.png" onerror="alert(1)">'
                ),
            },
        )
        self.assertEqual(create_response.status_code, 302)
        view_response = self.client.get("/pages/view/sanitized-page")
        self.assertIn(b"<strong>Safe text</strong>", view_response.data)
        self.assertNotIn(b"<script>alert", view_response.data)
        self.assertNotIn(b"unsafe", view_response.data)
        self.assertNotIn(b"onerror", view_response.data)
        self.assertNotIn(b"tracker.png", view_response.data)

        form_response = self.client.get("/pages/new")
        self.assertIn(b'id="image-files"', form_response.data)
        self.assertIn(b'id="image_upload_session"', form_response.data)
        self.assertIn(b"Insert at Cursor", form_response.data)

    def test_image_upload_limits_and_animation_are_enforced(self):
        self.app.config["IMAGE_MAX_FILE_BYTES"] = 10
        oversized_file_response = self.upload_image(str(uuid4()))
        self.assertEqual(oversized_file_response.status_code, 413)
        self.app.config["IMAGE_MAX_FILE_BYTES"] = 15 * 1024 * 1024

        self.app.config["IMAGE_MAX_BATCH_BYTES"] = 10
        oversized_batch_response = self.upload_image(str(uuid4()))
        self.assertEqual(oversized_batch_response.status_code, 413)
        self.app.config["IMAGE_MAX_BATCH_BYTES"] = 50 * 1024 * 1024

        self.app.config["IMAGE_MAX_PIXELS"] = 100
        excessive_pixels_response = self.client.post(
            "/images/upload",
            data={
                "upload_session": str(uuid4()),
                "images": (
                    self.make_image_upload(size=(11, 10)),
                    "too-many-pixels.png",
                ),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(excessive_pixels_response.status_code, 400)
        self.app.config["IMAGE_MAX_PIXELS"] = 40_000_000

        self.app.config["IMAGE_STORAGE_LIMIT_BYTES"] = 1
        storage_limit_response = self.upload_image(str(uuid4()))
        self.assertEqual(storage_limit_response.status_code, 400)
        self.app.config["IMAGE_STORAGE_LIMIT_BYTES"] = 45 * 1024 * 1024 * 1024

        first_frame = Image.new("RGB", (16, 16), (255, 0, 0))
        second_frame = Image.new("RGB", (16, 16), (0, 0, 255))
        animated_upload = io.BytesIO()
        first_frame.save(
            animated_upload,
            format="WEBP",
            save_all=True,
            append_images=[second_frame],
            duration=100,
            loop=0,
        )
        first_frame.close()
        second_frame.close()
        animated_upload.seek(0)
        animated_response = self.client.post(
            "/images/upload",
            data={
                "upload_session": str(uuid4()),
                "images": (animated_upload, "animated.webp"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(animated_response.status_code, 400)
        self.assertIn(b"animated", animated_response.data)

    def test_image_management_requires_a_valid_csrf_token(self):
        self.app.config["WTF_CSRF_ENABLED"] = True
        form_response = self.client.get("/pages/new")
        token_match = re.search(
            br'name="csrf_token"[^>]*value="([^"]+)"',
            form_response.data,
        )
        self.assertIsNotNone(token_match)
        csrf_token = token_match.group(1).decode()

        missing_token_response = self.client.post(
            "/images/upload",
            data={
                "upload_session": str(uuid4()),
                "images": (self.make_image_upload(), "map.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(missing_token_response.status_code, 400)

        valid_token_response = self.client.post(
            "/images/upload",
            data={
                "csrf_token": csrf_token,
                "upload_session": str(uuid4()),
                "images": (self.make_image_upload(), "map.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(valid_token_response.status_code, 201)

    def test_draft_image_permissions_deletion_and_cleanup(self):
        upload_session = str(uuid4())
        upload_response = self.upload_image(upload_session)
        self.assertEqual(upload_response.status_code, 201)
        uploaded_image = upload_response.get_json()["images"][0]

        self.login_as(self.other_user_id)
        session_response = self.client.get(f"/images/session/{upload_session}")
        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.get_json()["images"], [])
        self.assertEqual(
            self.client.get(uploaded_image["thumbnail_url"]).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(f"/images/{uploaded_image['id']}/delete").status_code,
            403,
        )
        cross_user_attach_response = self.client.post(
            "/pages/new",
            data={
                "image_upload_session": upload_session,
                "title": "Stolen Draft Image",
                "body_markdown": (
                    f"![Not mine]({uploaded_image['display_url']})"
                ),
            },
        )
        self.assertEqual(cross_user_attach_response.status_code, 200)
        self.assertIn(b"belongs to a different draft", cross_user_attach_response.data)

        self.login_as(self.user_id)
        delete_response = self.client.post(
            f"/images/{uploaded_image['id']}/delete"
        )
        self.assertEqual(delete_response.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(
                db.session.get(models.ImageAssets, uploaded_image["id"])
            )

        old_session = str(uuid4())
        old_image = self.upload_image(old_session).get_json()["images"][0]
        with self.app.app_context():
            from datetime import datetime, timedelta, timezone

            asset = db.session.get(models.ImageAssets, old_image["id"])
            asset.created_at = datetime.now(timezone.utc) - timedelta(days=31)
            db.session.commit()

        cleanup_response = self.app.test_cli_runner().invoke(
            args=["cleanup-images", "--days", "30"]
        )
        self.assertEqual(cleanup_response.exit_code, 0)
        self.assertIn("Removed 1 images.", cleanup_response.output)
        with self.app.app_context():
            self.assertIsNone(db.session.get(models.ImageAssets, old_image["id"]))

        orphan_image = self.upload_image(str(uuid4())).get_json()["images"][0]
        with self.app.app_context():
            from datetime import datetime, timedelta, timezone
            from image_service import get_asset_directory

            orphan_directory = get_asset_directory(orphan_image["id"])
            db.session.delete(
                db.session.get(models.ImageAssets, orphan_image["id"])
            )
            db.session.commit()
            old_timestamp = (
                datetime.now(timezone.utc) - timedelta(days=31)
            ).timestamp()
            os.utime(orphan_directory, (old_timestamp, old_timestamp))

        orphan_cleanup_response = self.app.test_cli_runner().invoke(
            args=["cleanup-images", "--days", "30"]
        )
        self.assertEqual(orphan_cleanup_response.exit_code, 0)
        self.assertIn(
            "Removed 1 orphaned image directories",
            orphan_cleanup_response.output,
        )
        self.assertFalse(orphan_directory.exists())

        storage_response = self.app.test_cli_runner().invoke(
            args=["image-storage-report"]
        )
        self.assertEqual(storage_response.exit_code, 0)
        self.assertIn(
            "0 tracked images using 0 bytes; image files use 0 bytes.",
            storage_response.output,
        )

        self.login_as(self.admin_id)
        official_response = self.client.post(
            "/pages/new",
            data={
                "title": "Official Illustrated Guide",
                "page_type": "official",
                "body_markdown": "Official content",
            },
        )
        self.assertEqual(official_response.status_code, 302)
        with self.app.app_context():
            official_page = models.Pages.query.filter_by(
                title="Official Illustrated Guide"
            ).one()
            official_page_id = official_page.id

        self.login_as(self.user_id)
        forbidden_upload = self.upload_image(
            str(uuid4()),
            page_id=official_page_id,
        )
        self.assertEqual(forbidden_upload.status_code, 403)


if __name__ == "__main__":
    unittest.main()
