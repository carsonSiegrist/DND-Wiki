#Construct and configure the app. 

import os
from datetime import datetime, timedelta, timezone

import click
from dotenv import load_dotenv
from flask import Flask

from extensions import db, limiter, login_manager, migrate

load_dotenv()

def create_app(test_config=None):
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["IMAGE_UPLOAD_ROOT"] = os.path.join(
        app.instance_path,
        "uploads",
        "images",
    )
    app.config["IMAGE_MAX_FILE_BYTES"] = 15 * 1024 * 1024
    app.config["IMAGE_MAX_BATCH_BYTES"] = 50 * 1024 * 1024
    app.config["IMAGE_MAX_FILES"] = 10
    app.config["IMAGE_MAX_PIXELS"] = 40_000_000
    app.config["IMAGE_STORAGE_LIMIT_BYTES"] = 45 * 1024 * 1024 * 1024
    app.config["MAX_CONTENT_LENGTH"] = 51 * 1024 * 1024
    app.config["RATELIMIT_STORAGE_URI"] = os.getenv(
        "RATELIMIT_STORAGE_URI",
        "memory://",
    )
    app.config["RATELIMIT_HEADERS_ENABLED"] = True

    if test_config is not None:
        app.config.update(test_config)

    validate_required_config(app)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    limiter.init_app(app)

    # Import models so SQLAlchemy and migrations know about them.
    import models

    # Blueprints: 
    from routes.main import main_bp
    from routes.auth import auth_bp
    from routes.images import images_bp
    from routes.pages import pages_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(images_bp)
    app.register_blueprint(pages_bp)

    @app.cli.command("rebuild-search-index")
    def rebuild_search_index_command():
        """Rebuild the current-page full-text search index."""
        from search import rebuild_search_index

        indexed_pages = rebuild_search_index()
        db.session.commit()
        click.echo(f"Indexed {indexed_pages} pages.")

    @app.cli.command("cleanup-images")
    @click.option(
        "--days",
        default=30,
        show_default=True,
        type=click.IntRange(min=1),
        help="Remove unreferenced uploads older than this many days.",
    )
    def cleanup_images_command(days):
        """Remove abandoned and no-longer-referenced image uploads."""
        from image_service import (
            cleanup_orphaned_image_files,
            cleanup_unreferenced_images,
            delete_asset_files,
        )

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        image_ids = cleanup_unreferenced_images(cutoff)
        db.session.commit()
        deletion_failures = []
        for image_id in image_ids:
            try:
                delete_asset_files(image_id)
            except OSError:
                deletion_failures.append(image_id)
                app.logger.exception(
                    "Could not remove image files for %s",
                    image_id,
                )
        orphan_count, temporary_count, failures = cleanup_orphaned_image_files(
            cutoff
        )
        click.echo(f"Removed {len(image_ids)} images.")
        click.echo(
            f"Removed {orphan_count} orphaned image directories and "
            f"{temporary_count} temporary uploads."
        )
        all_failures = deletion_failures + failures
        if all_failures:
            for failed_entry in failures:
                app.logger.error(
                    "Could not remove stale image filesystem entry %s",
                    failed_entry,
                )
            raise click.ClickException(
                f"Could not remove {len(all_failures)} filesystem entries; "
                "check the application log."
            )

    @app.cli.command("image-storage-report")
    def image_storage_report_command():
        """Report database-tracked and on-disk image storage usage."""
        from sqlalchemy import func
        from image_service import get_stored_image_bytes

        tracked_bytes = db.session.query(
            func.coalesce(
                func.sum(
                    models.ImageAssets.master_bytes
                    + models.ImageAssets.display_bytes
                    + models.ImageAssets.thumbnail_bytes
                ),
                0,
            )
        ).scalar()
        image_count = models.ImageAssets.query.count()
        stored_bytes = get_stored_image_bytes(include_temporary=True)
        click.echo(
            f"{image_count} tracked images using {tracked_bytes} bytes; "
            f"image files use {stored_bytes} bytes."
        )

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault(
            "Content-Security-Policy",
            "img-src 'self'; object-src 'none'; base-uri 'self'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    return app


def validate_required_config(app):
    missing_settings = [
        setting
        for setting in ("SECRET_KEY", "SQLALCHEMY_DATABASE_URI")
        if not str(app.config.get(setting) or "").strip()
    ]
    if missing_settings:
        names = ", ".join(missing_settings)
        raise RuntimeError(
            f"Missing required application configuration: {names}. "
            "Set SECRET_KEY and DATABASE_URL before starting the wiki."
        )


app = create_app()


if __name__ == "__main__":
    app.run()
