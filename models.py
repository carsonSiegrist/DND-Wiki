from datetime import datetime, timezone
from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from flask_login import UserMixin

from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="user"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    session_version: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )

    def set_password(self, password: str) -> None:
        """Set the user's password hash."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Check if the provided password matches the user's password hash."""
        return check_password_hash(self.password_hash, password)

    def get_id(self) -> str:
        """Include a revocable version in Flask-Login's signed session."""
        return f"{self.id}:{self.session_version}"


class InviteKeys(db.Model):
    __tablename__ = "invite_keys"

    id: Mapped[int] = mapped_column(primary_key=True)

    key_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    used_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    used_by: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id"),
        nullable=True,
    )


class PasswordResetTokens(db.Model):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    used_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )



class Categories(db.Model):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False
    )

    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False
    )

    description: Mapped[str] = mapped_column(
        String(255),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    created_by: Mapped[int] = mapped_column(
        db.ForeignKey("users.id"),
        nullable=False
    )

class Pages(db.Model):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False
    )

    slug: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False
    )

    page_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    created_by: Mapped[int] = mapped_column(
        db.ForeignKey("users.id"),
        nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    session_number: Mapped[int] = mapped_column(
        nullable=True
    )

    current_revision_id: Mapped[int] = mapped_column(
        db.ForeignKey("page_revisions.id"),
        nullable=True
    )


class PageTitleAliases(db.Model):
    __tablename__ = "page_title_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)

    page_id: Mapped[int] = mapped_column(
        db.ForeignKey("pages.id"),
        nullable=True
    )

    title: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )


class PageUpdateAuthors(db.Model):
    __tablename__ = "page_update_authors"

    page_id: Mapped[int] = mapped_column(
        db.ForeignKey("pages.id"),
        primary_key=True
    )

    user_id: Mapped[int] = mapped_column(
        db.ForeignKey("users.id"),
        nullable=False
    )


class PageCategories(db.Model):
    __tablename__ = "page_categories"

    page_id: Mapped[int] = mapped_column(
        db.ForeignKey("pages.id"),
        nullable=False,
        primary_key=True
    )

    category_id: Mapped[int] = mapped_column(
        db.ForeignKey("categories.id"),
        nullable=False,
        primary_key=True
    )

class PageRevisions(db.Model):
    __tablename__ = "page_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)

    page_id: Mapped[int] = mapped_column(
        db.ForeignKey("pages.id"),
        nullable=False
    )

    author_id: Mapped[int] = mapped_column(
        db.ForeignKey("users.id"),
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    body_markdown: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    edit_summary: Mapped[str] = mapped_column(
        String(512),
        nullable=True
    )

    page_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    session_number: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    revision_number: Mapped[int] = mapped_column(
        nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint('page_id', 'revision_number', name='unique_page_revision'),
    )


class PageRevisionCategories(db.Model):
    __tablename__ = "page_revision_categories"

    id: Mapped[int] = mapped_column(primary_key=True)

    revision_id: Mapped[int] = mapped_column(
        db.ForeignKey("page_revisions.id"),
        nullable=False,
        index=True,
    )

    category_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("categories.id"),
        nullable=True,
    )

    category_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint(
            "revision_id",
            "category_name",
            name="unique_revision_category_name",
        ),
    )


class PageRevisionTitles(db.Model):
    __tablename__ = "page_revision_titles"

    revision_id: Mapped[int] = mapped_column(
        db.ForeignKey("page_revisions.id"),
        primary_key=True
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )

class PageLinks(db.Model):
    __tablename__ = "page_links"

    id: Mapped[int] = mapped_column(primary_key=True)

    source_page_id: Mapped[int] = mapped_column(
        db.ForeignKey("pages.id"),
        nullable=False
    )

    target_page_id: Mapped[int] = mapped_column(
        db.ForeignKey("pages.id"),
        nullable=True
    )

    target_title: Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint('source_page_id', 'target_title', name='unique_page_link'),
        db.UniqueConstraint('source_page_id', 'target_page_id', name='unique_page_target'),
    )


class ImageAssets(db.Model):
    __tablename__ = "image_assets"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    page_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("pages.id"),
        nullable=True,
        index=True,
    )

    upload_session: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    uploaded_by: Mapped[int] = mapped_column(
        db.ForeignKey("users.id"),
        nullable=False,
    )

    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    width: Mapped[int] = mapped_column(nullable=False)
    height: Mapped[int] = mapped_column(nullable=False)
    master_bytes: Mapped[int] = mapped_column(nullable=False)
    display_bytes: Mapped[int] = mapped_column(nullable=False)
    thumbnail_bytes: Mapped[int] = mapped_column(nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class RevisionImages(db.Model):
    __tablename__ = "revision_images"

    revision_id: Mapped[int] = mapped_column(
        db.ForeignKey("page_revisions.id"),
        primary_key=True,
    )

    image_id: Mapped[str] = mapped_column(
        db.ForeignKey("image_assets.id"),
        primary_key=True,
        index=True,
    )
