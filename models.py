from datetime import datetime, timezone
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from werkzeug.security import generate_password_hash, check_password_hash

from app import db


class User(db.Model):
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

    def set_password(self, password: str) -> None:
        """Set the user's password hash."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Check if the provided password matches the user's password hash."""
        return check_password_hash(self.password_hash, password)


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

    revision_number: Mapped[int] = mapped_column(
        nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint('page_id', 'revision_number', name='unique_page_revision'),
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
    )