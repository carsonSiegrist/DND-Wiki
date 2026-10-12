"""Authenticated image uploads and revision-aware image delivery."""

from uuid import UUID

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_login import current_user, login_required
from flask_wtf.csrf import validate_csrf
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import RequestEntityTooLarge
from wtforms.validators import ValidationError

import models
from extensions import db, limiter
from image_service import (
    ImageValidationError,
    delete_asset_files,
    get_variant_path,
    image_to_dict,
    process_uploaded_image,
)


images_bp = Blueprint("images", __name__, url_prefix="/images")

ADMIN_ROLE = "admin"
REGULAR_PAGE_TYPES = {"article", "recap"}
DEFAULT_MAX_BATCH_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_FILES = 10
DEFAULT_MAX_FILE_BYTES = 15 * 1024 * 1024


def _error(message, status_code):
    return jsonify(error=message), status_code


def _is_admin():
    return current_user.is_authenticated and current_user.role == ADMIN_ROLE


def _can_edit_page(page):
    return _is_admin() or page.page_type in REGULAR_PAGE_TYPES


def _canonical_uuid(value, description):
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError):
        raise ImageValidationError(f"The {description} is invalid.")


def _validate_request_csrf():
    if not current_app.config.get("WTF_CSRF_ENABLED", True):
        return
    token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    try:
        validate_csrf(token)
    except ValidationError as error:
        raise ImageValidationError(
            "The form expired or could not be verified. Reload the page and try again."
        ) from error


def _requested_page():
    raw_page_id = request.values.get("page_id")
    if raw_page_id in {None, ""}:
        return None, None
    try:
        page_id = int(raw_page_id)
    except (TypeError, ValueError):
        return None, _error("The page identifier is invalid.", 400)
    page = db.session.get(models.Pages, page_id)
    if page is None:
        return None, _error("The requested page does not exist.", 404)
    if not _can_edit_page(page):
        return None, _error("You do not have permission to add images to that page.", 403)
    return page, None


def _uploaded_file_size(upload):
    try:
        position = upload.stream.tell()
        upload.stream.seek(0, 2)
        size = upload.stream.tell()
        upload.stream.seek(position)
        return size
    except (AttributeError, OSError):
        return upload.content_length


def _remove_asset_files_safely(asset_or_id):
    try:
        delete_asset_files(asset_or_id)
    except OSError:
        image_id = getattr(asset_or_id, "id", asset_or_id)
        current_app.logger.exception(
            "Could not remove image files for %s",
            image_id,
        )


@images_bp.before_request
def require_authentication_for_image_management():
    public_endpoint = request.endpoint == "images.serve_image"
    if not public_endpoint and not current_user.is_authenticated:
        return _error("Log in to manage wiki images.", 401)
    return None


@images_bp.errorhandler(RequestEntityTooLarge)
def upload_too_large(_error_value):
    return _error("The selected images exceed the batch upload limit.", 413)


@images_bp.route("/upload", methods=["POST"])
@login_required
@limiter.limit("60 per hour")
def upload_images():
    try:
        _validate_request_csrf()
        upload_session = _canonical_uuid(
            request.form.get("upload_session"),
            "upload session",
        )
    except ImageValidationError as error:
        return _error(str(error), 400)

    page, page_error = _requested_page()
    if page_error is not None:
        return page_error

    uploads = [upload for upload in request.files.getlist("images") if upload]
    max_files = current_app.config.get("IMAGE_MAX_FILES", DEFAULT_MAX_FILES)
    if not uploads:
        return _error("Choose at least one image to upload.", 400)
    if len(uploads) > max_files:
        return _error(f"Choose no more than {max_files} images at a time.", 400)

    max_file_bytes = current_app.config.get(
        "IMAGE_MAX_FILE_BYTES",
        DEFAULT_MAX_FILE_BYTES,
    )
    max_batch_bytes = current_app.config.get(
        "IMAGE_MAX_BATCH_BYTES",
        DEFAULT_MAX_BATCH_BYTES,
    )
    known_sizes = [_uploaded_file_size(upload) for upload in uploads]
    for upload, size in zip(uploads, known_sizes):
        if size is not None and size > max_file_bytes:
            return _error(
                f"{upload.filename or 'An image'} is larger than the "
                f"{max_file_bytes // (1024 * 1024)} MB upload limit.",
                413,
            )
    if (
        all(size is not None for size in known_sizes)
        and sum(known_sizes) > max_batch_bytes
    ):
        return _error("The selected images exceed the batch upload limit.", 413)

    assets = []
    errors = []
    actual_batch_bytes = 0
    for upload in uploads:
        asset = None
        try:
            asset, source_bytes = process_uploaded_image(
                upload,
                upload_session,
                current_user.id,
            )
            actual_batch_bytes += source_bytes
            if actual_batch_bytes > max_batch_bytes:
                _remove_asset_files_safely(asset)
                errors.append(
                    f"{asset.original_filename} was skipped because the batch "
                    "upload limit was reached."
                )
                continue
            db.session.add(asset)
            assets.append(asset)
        except ImageValidationError as error:
            errors.append(str(error))
        except Exception:
            if asset is not None:
                _remove_asset_files_safely(asset)
            current_app.logger.exception("Unexpected image processing failure")
            errors.append(
                f"{upload.filename or 'An image'} could not be processed."
            )

    if not assets:
        db.session.rollback()
        message = errors[0] if errors else "No images could be uploaded."
        return jsonify(error=message, errors=errors), 400

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        for asset in assets:
            _remove_asset_files_safely(asset)
        return _error("The images could not be saved. Please try again.", 409)
    except Exception:
        db.session.rollback()
        for asset in assets:
            _remove_asset_files_safely(asset)
        current_app.logger.exception("Image upload database commit failed")
        return _error("The images could not be saved. Please try again.", 500)

    return jsonify(
        images=[image_to_dict(asset) for asset in assets],
        errors=errors,
    ), 201


@images_bp.route("/session/<upload_session>", methods=["GET"])
@login_required
def session_images(upload_session):
    try:
        upload_session = _canonical_uuid(upload_session, "upload session")
    except ImageValidationError as error:
        return _error(str(error), 400)

    page, page_error = _requested_page()
    if page_error is not None:
        return page_error

    own_draft_filter = (
        (models.ImageAssets.upload_session == upload_session)
        & (models.ImageAssets.uploaded_by == current_user.id)
        & models.ImageAssets.page_id.is_(None)
    )
    if page is None:
        query = models.ImageAssets.query.filter(own_draft_filter)
    else:
        query = models.ImageAssets.query.filter(
            or_(
                own_draft_filter,
                models.ImageAssets.page_id == page.id,
            )
        )

    assets = query.order_by(
        models.ImageAssets.created_at.asc(),
        models.ImageAssets.id.asc(),
    ).all()
    return jsonify(images=[image_to_dict(asset) for asset in assets])


@images_bp.route("/<image_id>/delete", methods=["POST"])
@login_required
def delete_image(image_id):
    try:
        _validate_request_csrf()
        image_id = _canonical_uuid(image_id, "image identifier")
    except ImageValidationError as error:
        return _error(str(error), 400)

    asset = db.session.get(models.ImageAssets, image_id)
    if asset is None:
        return _error("The image does not exist.", 404)
    if asset.uploaded_by != current_user.id and not _is_admin():
        return _error("You do not have permission to delete that image.", 403)

    is_referenced = models.RevisionImages.query.filter_by(
        image_id=asset.id
    ).first() is not None
    if is_referenced:
        return _error(
            "That image is used by a saved page revision and cannot be deleted.",
            409,
        )

    db.session.delete(asset)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Image upload deletion failed")
        return _error("The image could not be deleted. Please try again.", 500)

    # The DB remains authoritative; cleanup reconciles any filesystem failure.
    _remove_asset_files_safely(image_id)
    return jsonify(deleted=image_id)


@images_bp.route("/<image_id>/<variant>", methods=["GET"])
def serve_image(image_id, variant):
    try:
        image_id = _canonical_uuid(image_id, "image identifier")
        image_path = get_variant_path(image_id, variant)
    except ImageValidationError as error:
        return _error(str(error), 404)

    asset = db.session.get(models.ImageAssets, image_id)
    if asset is None or not image_path.is_file():
        return _error("The image does not exist.", 404)

    is_referenced = models.RevisionImages.query.filter_by(
        image_id=asset.id
    ).first() is not None
    may_view_draft = (
        current_user.is_authenticated
        and (asset.uploaded_by == current_user.id or _is_admin())
    )
    if not is_referenced and not may_view_draft:
        return _error("You do not have permission to view that image.", 403)

    response = send_file(
        image_path,
        mimetype="image/webp",
        conditional=True,
        etag=True,
        max_age=31536000 if is_referenced else 0,
    )
    if is_referenced:
        response.cache_control.public = True
        response.cache_control.max_age = 31536000
        response.cache_control.immutable = True
    else:
        response.cache_control.public = False
        response.cache_control.private = True
        response.cache_control.no_store = True
        response.cache_control.max_age = 0
    return response
