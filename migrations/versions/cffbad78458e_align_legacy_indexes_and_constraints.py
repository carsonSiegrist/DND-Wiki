"""align legacy indexes and constraints

Revision ID: cffbad78458e
Revises: eb045642319a
Create Date: 2026-10-12 16:43:24.525280

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cffbad78458e'
down_revision = 'eb045642319a'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())

    image_indexes = {
        index["name"] for index in inspector.get_indexes("image_assets")
    }
    if "ix_image_assets_page_id" not in image_indexes:
        op.create_index(
            "ix_image_assets_page_id",
            "image_assets",
            ["page_id"],
            unique=False,
        )

    revision_image_indexes = {
        index["name"] for index in inspector.get_indexes("revision_images")
    }
    if "ix_revision_images_image_id" not in revision_image_indexes:
        op.create_index(
            "ix_revision_images_image_id",
            "revision_images",
            ["image_id"],
            unique=False,
        )

    page_link_unique_columns = {
        frozenset(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("page_links")
    }
    if frozenset({"source_page_id", "target_page_id"}) not in (
        page_link_unique_columns
    ):
        with op.batch_alter_table("page_links") as batch_op:
            batch_op.create_unique_constraint(
                "unique_page_target",
                ["source_page_id", "target_page_id"],
            )


def downgrade():
    # This compatibility migration only fills schema objects missing from old
    # create_all()-managed databases. The baseline owns these objects.
    pass
