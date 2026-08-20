from app import app, db
import models 



with app.app_context(): 
    try: #Try to catch any exceptions that may occur during the test, and rollback the session to clean up after the test
        db.create_all()

        #--------------------
        #User Test
        #--------------------
        print("Running User Test...")
        user = models.User(
            username="testuser",
            email="testemail@test.com",
        )

        user.set_password("testpassword")

        db.session.add(user)
        db.session.flush()


        found_user = models.User.query.filter_by(username="testuser").first()

        assert found_user is not None, "User not found!"
        assert found_user.username == "testuser", "Username does not match!"
        assert found_user.email == "testemail@test.com", "Email does not match!"
        assert user.check_password("testpassword"), "Password check failed!"
        assert not user.check_password("wrongpassword"), "Password check should fail for wrong password!"
        assert found_user.role == "user", "Default role should be 'user'!"
        assert found_user.created_at is not None, "created_at should not be None!"
        assert found_user.id is not None, "User ID should not be None!"

        print("User Test completed!\n")

        #--------------------
        #Category Test
        #--------------------
        print("Running Category Test...")
        category = models.Categories(
            name="Test Category",
            slug="test-category",
            description="This is a test category.",
            created_by=user.id,
        )
        db.session.add(category)
        db.session.flush()

        assert category.name == "Test Category", "Category name does not match!"
        assert category.slug == "test-category", "Category slug does not match!"
        assert category.description == "This is a test category.", "Category description does not match!"
        assert category.created_by == user.id, "Category created_by does not match!"
        assert category.id is not None, "Category ID should not be None!"
        assert category.created_at is not None, "Category created_at should not be None!"

        print("Category Test completed!\n")
    
        #--------------------
        #Pages Test
        #--------------------
        print("Running Pages Test...")
        page = models.Pages(
            title="Test Page",
            slug="test-page",
            page_type="recap",
            created_by=user.id,
            session_number=1
        )
        db.session.add(page)
        db.session.flush()

        assert page.title == "Test Page", "Page title does not match!"
        assert page.slug == "test-page", "Page slug does not match!"
        assert page.page_type == "recap", "Page type does not match!"
        assert page.created_by == user.id, "Page created_by does not match!"
        assert page.session_number == 1, "Page session_number does not match!"
        assert page.id is not None, "Page ID should not be None!"
        assert page.created_at is not None, "Page created_at should not be None!"
        assert page.updated_at is not None, "Page updated_at should not be None!"
        assert page.current_revision_id is None, "Page current_revision_id should be None!"

        print("Pages Test completed!\n")

        #--------------------
        #Page Categories Test
        #--------------------
        print("Running Page Categories Test...")
        page_category = models.PageCategories(
            page_id=page.id,
            category_id=category.id
        )
        db.session.add(page_category)
        db.session.flush()

        assert page_category.page_id == page.id, "PageCategory page_id does not match!"
        assert page_category.category_id == category.id, "PageCategory category_id does not match!"

        print("Page Categories Test completed!\n")

        #--------------------
        #Page Revisions Test
        #--------------------
        print("Running Page Revisions Test...")
        page_revision = models.PageRevisions(
            page_id=page.id,
            author_id=user.id,
            body_markdown="This is a test page revision.",
            edit_summary="Initial revision.",
            revision_number=1
        )
        db.session.add(page_revision)
        db.session.flush()

        assert page_revision.id is not None, "PageRevision ID should not be None!"
        assert page_revision.page_id == page.id, "PageRevision page_id does not match!"
        assert page_revision.author_id == user.id, "PageRevision author_id does not match!"
        assert page_revision.body_markdown == "This is a test page revision.", "PageRevision body_markdown does not match!"
        assert page_revision.created_at is not None, "PageRevision created_at should not be None!"
        assert page_revision.edit_summary == "Initial revision.", "PageRevision edit_summary does not match!"
        assert page_revision.revision_number == 1, "PageRevision revision_number does not match!"

        #Test updating the page's current_revision_id
        page.current_revision_id = page_revision.id
        db.session.flush()

        assert page.current_revision_id == page_revision.id, "Page current_revision_id does not match PageRevision ID!"

        #Test unique constraint on revision_number for the same 
        duplicate_rejected = False
        try:
            duplicate_revision = models.PageRevisions(
                page_id=page.id,
                author_id=user.id,
                body_markdown="This is a duplicate test page revision.",
                edit_summary="Duplicate revision.",
                revision_number=1  # Same revision number as the previous one
            )
            db.session.add(duplicate_revision)
            db.session.flush()
            assert False, "Unique constraint on revision_number for the same page should have failed!"
        except Exception as e:
            duplicate_rejected = True
            db.session.rollback()  # Rollback the session to clean up after the test

        assert duplicate_rejected, "Unique constraint on revision_number for the same page was not enforced!"


        print("Page Revisions Test completed!\n")

        #--------------------
        #Page Links Test
        #--------------------
        print("Running Page Links Test...")
        page_link = models.PageLinks(
            source_page_id=page.id,
            target_page_id=page.id,  # Linking to itself for test purposes
            target_title="Test Page"
        )
        db.session.add(page_link)
        db.session.flush()

        assert page_link.id is not None, "PageLink ID should not be None!"
        assert page_link.source_page_id == page.id, "PageLink source_page_id does not match!"
        assert page_link.target_page_id == page.id, "PageLink target_page_id does not match!"
        assert page_link.target_title == "Test Page", "PageLink target_title does not match!"

        #Test unique constraint on source_page_id and target_page_title
        duplicate_link_rejected = False
        try:
            duplicate_link = models.PageLinks(
                source_page_id=page.id,
                target_page_id=page.id, 
                target_title="Test Page" # Same target title as the previous one
            )
            db.session.add(duplicate_link)
            db.session.flush()
            assert False, "Unique constraint on source_page_id and target_page_title should have failed!"
        except Exception as e:
            duplicate_link_rejected = True
            db.session.rollback()  # Rollback the session to clean up after the test

        assert duplicate_link_rejected, "Unique constraint on source_page_id and target_page_title was not enforced!"

        #Test null target page 
        page_link_null_target = models.PageLinks(
            source_page_id=page.id,
            target_page_id=None,  # Null target page
            target_title="Test Page Null Target"
        )
        db.session.add(page_link_null_target)
        db.session.flush()

        assert page_link_null_target.id is not None, "PageLink with null target ID should not be None!"
        assert page_link_null_target.source_page_id == page.id, "PageLink with null target source_page_id does not match!"
        assert page_link_null_target.target_page_id is None, "PageLink with null target target_page_id should be None!"
        assert page_link_null_target.target_title == "Test Page Null Target", "PageLink with null target target_title does not match!"

        print("Page Links Test completed!\n")

    except Exception as e:
        print(f"An error occurred during the tests: {e}")

    finally:
        db.session.rollback()  # Rollback the session to clean up after the test