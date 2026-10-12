"""Image validation, storage, revision attachment, and HTML sanitizing helpers."""

from __future__ import annotations

try:
    import fcntl
except ImportError:  # Windows fallback still serializes threads in one process.
    fcntl = None

import os
import re
import shutil
import tempfile
import warnings
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

import bleach
import markdown
from flask import current_app, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import exists

import models
from extensions import db


DEFAULT_MAX_FILE_BYTES = 15 * 1024 * 1024
DEFAULT_MAX_PIXELS = 40_000_000
DEFAULT_STORAGE_LIMIT_BYTES = 45 * 1024 * 1024 * 1024
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
IMAGE_VARIANT_SIZES = {
    "master": 6000,
    "display": 2000,
    "thumbnail": 320,
}
IMAGE_VARIANT_QUALITY = {
    "master": 90,
    "display": 86,
    "thumbnail": 80,
}
UUID_PATTERN = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)
LOCAL_IMAGE_URL_PATTERN = re.compile(
    rf"/images/(?P<image_id>{UUID_PATTERN})/(?:thumbnail|display|master)"
)
IMAGE_TAG_PATTERN = re.compile(r"<img\b[^>]*>")
DANGEROUS_HTML_BLOCK_PATTERN = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
IMAGE_STORAGE_THREAD_LOCK = Lock()


class ImageValidationError(ValueError):
    """An image or image reference failed user-correctable validation."""


def normalize_uuid(value, label="identifier"):
    """Return a canonical UUID string or raise a user-facing validation error."""
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise ImageValidationError(f"The image {label} is invalid.") from error


def get_upload_root():
    configured_root = current_app.config.get("IMAGE_UPLOAD_ROOT")
    if configured_root:
        root = Path(configured_root)
        if not root.is_absolute():
            root = Path(current_app.instance_path) / root
    else:
        root = Path(current_app.instance_path) / "uploads" / "images"
    return root.resolve()


def get_asset_directory(asset_or_id):
    image_id = getattr(asset_or_id, "id", asset_or_id)
    image_id = normalize_uuid(image_id)
    return get_upload_root() / image_id[:2] / image_id[2:4] / image_id


def get_variant_path(asset_or_id, variant):
    if variant not in IMAGE_VARIANT_SIZES:
        raise ImageValidationError("That image size is not available.")
    return get_asset_directory(asset_or_id) / f"{variant}.webp"


@contextmanager
def image_storage_lock():
    """Serialize quota checks across threads and supported server processes."""
    root = get_upload_root()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".storage.lock"
    with IMAGE_STORAGE_THREAD_LOCK:
        with lock_path.open("a+b") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def get_stored_image_bytes(include_temporary=False):
    """Return bytes stored under the image root.

    Temporary files are excluded from quota calculations but can be included
    in operational reports.
    """
    root = get_upload_root()
    if not root.exists():
        return 0

    total = 0
    for directory, child_directories, filenames in os.walk(root):
        if not include_temporary:
            child_directories[:] = [
                name for name in child_directories if name != ".tmp"
            ]
        for filename in filenames:
            try:
                total += (Path(directory) / filename).stat().st_size
            except FileNotFoundError:
                # A concurrent cleanup may remove an image during this estimate.
                continue
    return total


def _clean_filename(filename):
    filename = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename:
        return "image"
    return filename[:255]


def _copy_upload(upload, destination):
    max_bytes = current_app.config.get(
        "IMAGE_MAX_FILE_BYTES",
        DEFAULT_MAX_FILE_BYTES,
    )
    bytes_written = 0
    try:
        upload.stream.seek(0)
    except (AttributeError, OSError):
        pass

    with destination.open("xb") as output:
        while True:
            chunk = upload.stream.read(1024 * 1024)
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > max_bytes:
                raise ImageValidationError(
                    f"{_clean_filename(upload.filename)} is larger than the "
                    f"{max_bytes // (1024 * 1024)} MB upload limit."
                )
            output.write(chunk)

    if bytes_written == 0:
        raise ImageValidationError(
            f"{_clean_filename(upload.filename)} is empty."
        )
    return bytes_written


def _open_and_normalize_image(source_path, original_filename):
    max_pixels = current_app.config.get("IMAGE_MAX_PIXELS", DEFAULT_MAX_PIXELS)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source_path) as source_image:
                image_format = (source_image.format or "").upper()
                if image_format not in IMAGE_FORMATS:
                    raise ImageValidationError(
                        f"{original_filename} is not a JPEG, PNG, or WebP image."
                    )
                if getattr(source_image, "is_animated", False) or getattr(
                    source_image,
                    "n_frames",
                    1,
                ) != 1:
                    raise ImageValidationError(
                        f"{original_filename} is animated; "
                        "animated images are not supported."
                    )

                width, height = source_image.size
                if width < 1 or height < 1 or width * height > max_pixels:
                    raise ImageValidationError(
                        f"{original_filename} exceeds the "
                        f"{max_pixels:,}-pixel limit."
                    )

                source_image.load()
                transposed_image = ImageOps.exif_transpose(source_image)
                try:
                    width, height = transposed_image.size
                    has_transparency = transposed_image.mode in {"RGBA", "LA"} or (
                        transposed_image.mode == "P"
                        and "transparency" in transposed_image.info
                    )
                    image = transposed_image.convert(
                        "RGBA" if has_transparency else "RGB"
                    )
                finally:
                    if transposed_image is not source_image:
                        transposed_image.close()
                return image, width, height
    except ImageValidationError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as error:
        raise ImageValidationError(
            f"{original_filename} is not a valid supported image."
        ) from error


def _write_variants(image, directory):
    byte_sizes = {}
    try:
        for variant, maximum_dimension in IMAGE_VARIANT_SIZES.items():
            resized = image.copy()
            try:
                resized.thumbnail(
                    (maximum_dimension, maximum_dimension),
                    Image.Resampling.LANCZOS,
                )
                destination = directory / f"{variant}.webp"
                resized.save(
                    destination,
                    format="WEBP",
                    quality=IMAGE_VARIANT_QUALITY[variant],
                    method=6,
                )
                byte_sizes[variant] = destination.stat().st_size
            finally:
                resized.close()
    except (OSError, ValueError) as error:
        raise ImageValidationError(
            "The server could not process that image. Please try another file."
        ) from error
    return byte_sizes


def process_uploaded_image(upload, upload_session, user_id):
    """Validate and atomically persist one upload, returning its model and size."""
    upload_session = normalize_uuid(upload_session, "upload session")
    original_filename = _clean_filename(upload.filename)
    root = get_upload_root()
    temporary_root = root / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)

    image_id = str(uuid4())
    while get_asset_directory(image_id).exists():
        image_id = str(uuid4())

    temporary_directory = Path(
        tempfile.mkdtemp(prefix=f"{image_id}-", dir=temporary_root)
    )
    final_directory = get_asset_directory(image_id)
    moved_to_final = False
    source_path = temporary_directory / "upload.bin"

    try:
        source_bytes = _copy_upload(upload, source_path)
        image, width, height = _open_and_normalize_image(
            source_path,
            original_filename,
        )
        try:
            variant_sizes = _write_variants(image, temporary_directory)
        finally:
            image.close()
        source_path.unlink()

        new_bytes = sum(variant_sizes.values())
        with image_storage_lock():
            storage_limit = current_app.config.get(
                "IMAGE_STORAGE_LIMIT_BYTES",
                DEFAULT_STORAGE_LIMIT_BYTES,
            )
            if get_stored_image_bytes() + new_bytes > storage_limit:
                raise ImageValidationError(
                    "The wiki image storage limit has been reached. "
                    "Contact an administrator."
                )

            final_directory.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary_directory, final_directory)
            moved_to_final = True

        asset = models.ImageAssets(
            id=image_id,
            page_id=None,
            upload_session=upload_session,
            uploaded_by=user_id,
            original_filename=original_filename,
            width=width,
            height=height,
            master_bytes=variant_sizes["master"],
            display_bytes=variant_sizes["display"],
            thumbnail_bytes=variant_sizes["thumbnail"],
        )
        return asset, source_bytes
    except Exception:
        if moved_to_final:
            shutil.rmtree(final_directory, ignore_errors=True)
        else:
            shutil.rmtree(temporary_directory, ignore_errors=True)
        raise


class _RenderedImageReferenceParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.image_ids = []
        self._seen_ids = set()

    def handle_starttag(self, tag, attributes):
        reference_attribute = {"img": "src", "a": "href"}.get(tag)
        if reference_attribute is None:
            return

        attribute_values = dict(attributes)
        reference = attribute_values.get(reference_attribute, "")
        match = LOCAL_IMAGE_URL_PATTERN.fullmatch(reference)
        if match is None:
            return

        image_id = str(UUID(match.group("image_id")))
        if image_id not in self._seen_ids:
            self.image_ids.append(image_id)
            self._seen_ids.add(image_id)


def extract_image_ids(markdown_text):
    """Return local images that the rendered and sanitized page references."""
    rendered_html = markdown.markdown(markdown_text or "")
    parser = _RenderedImageReferenceParser()
    parser.feed(sanitize_rendered_html(rendered_html))
    parser.close()
    return parser.image_ids


def attach_revision_images(page, revision, body_markdown, upload_session, user):
    """Validate image references and associate them with a saved revision."""
    image_ids = extract_image_ids(body_markdown)
    if not image_ids:
        return []

    user_id = getattr(user, "id", user)
    assets = models.ImageAssets.query.filter(
        models.ImageAssets.id.in_(image_ids)
    ).all()
    assets_by_id = {asset.id: asset for asset in assets}
    missing_ids = [
        image_id for image_id in image_ids if image_id not in assets_by_id
    ]
    if missing_ids:
        raise ImageValidationError(
            "The page refers to an image that no longer exists. Remove it or upload it again."
        )

    unbound_assets = [asset for asset in assets if asset.page_id is None]
    normalized_session = None
    if unbound_assets:
        if not upload_session:
            raise ImageValidationError(
                "An uploaded image could not be verified for this draft. Upload it again."
            )
        normalized_session = normalize_uuid(upload_session, "upload session")

    ordered_assets = []
    for image_id in image_ids:
        asset = assets_by_id[image_id]
        if asset.page_id is None:
            if (
                asset.uploaded_by != user_id
                or asset.upload_session != normalized_session
            ):
                raise ImageValidationError(
                    "An uploaded image belongs to a different draft. "
                    "Remove it or upload it again."
                )
            asset.page_id = page.id
        elif asset.page_id != page.id:
            raise ImageValidationError(
                "An image from another page cannot be attached here. Upload a new copy."
            )

        association = db.session.get(
            models.RevisionImages,
            (revision.id, asset.id),
        )
        if association is None:
            db.session.add(
                models.RevisionImages(
                    revision_id=revision.id,
                    image_id=asset.id,
                )
            )
        ordered_assets.append(asset)

    return ordered_assets


def delete_asset_files(asset_or_id):
    """Remove one UUID-scoped asset directory after its DB row is committed away."""
    asset_directory = get_asset_directory(asset_or_id)
    try:
        asset_directory.lstat()
    except FileNotFoundError:
        return

    if asset_directory.is_symlink():
        asset_directory.unlink()
    else:
        shutil.rmtree(asset_directory)

    root = get_upload_root()
    for directory in (asset_directory.parent, asset_directory.parent.parent):
        if directory == root:
            break
        try:
            directory.rmdir()
        except (FileNotFoundError, OSError):
            break


def cleanup_orphaned_image_files(cutoff):
    """Remove stale temporary files and UUID directories absent from the DB."""
    root = get_upload_root()
    if not root.exists():
        return 0, 0, []

    cutoff_timestamp = cutoff.timestamp()
    tracked_ids = {
        image_id
        for image_id, in db.session.query(models.ImageAssets.id).all()
    }
    removed_orphans = 0
    removed_temporary = 0
    failures = []

    temporary_root = root / ".tmp"
    if temporary_root.is_dir() and not temporary_root.is_symlink():
        for temporary_path in temporary_root.iterdir():
            try:
                if temporary_path.lstat().st_mtime >= cutoff_timestamp:
                    continue
                if temporary_path.is_symlink() or not temporary_path.is_dir():
                    temporary_path.unlink()
                else:
                    shutil.rmtree(temporary_path)
                removed_temporary += 1
            except FileNotFoundError:
                continue
            except OSError:
                failures.append(str(temporary_path))

    for first_prefix in root.iterdir():
        if (
            first_prefix.name == ".tmp"
            or first_prefix.is_symlink()
            or not first_prefix.is_dir()
            or re.fullmatch(r"[0-9a-f]{2}", first_prefix.name) is None
        ):
            continue
        for second_prefix in first_prefix.iterdir():
            if (
                second_prefix.is_symlink()
                or not second_prefix.is_dir()
                or re.fullmatch(r"[0-9a-f]{2}", second_prefix.name) is None
            ):
                continue
            for asset_directory in second_prefix.iterdir():
                try:
                    image_id = str(UUID(asset_directory.name))
                except (AttributeError, TypeError, ValueError):
                    continue
                if (
                    image_id != asset_directory.name
                    or image_id[:2] != first_prefix.name
                    or image_id[2:4] != second_prefix.name
                    or image_id in tracked_ids
                ):
                    continue
                try:
                    if asset_directory.lstat().st_mtime >= cutoff_timestamp:
                        continue
                    delete_asset_files(image_id)
                    removed_orphans += 1
                except FileNotFoundError:
                    continue
                except OSError:
                    failures.append(str(asset_directory))

    return removed_orphans, removed_temporary, failures


def delete_page_image_records(page_id, revision_ids):
    """Delete a page's image rows and return IDs for post-commit file removal."""
    revision_ids = list(revision_ids)
    asset_ids = [
        image_id
        for image_id, in db.session.query(models.ImageAssets.id).filter_by(
            page_id=page_id
        )
    ]

    if revision_ids:
        models.RevisionImages.query.filter(
            models.RevisionImages.revision_id.in_(revision_ids)
        ).delete(synchronize_session=False)
    if asset_ids:
        models.ImageAssets.query.filter(
            models.ImageAssets.id.in_(asset_ids)
        ).delete(synchronize_session=False)
    return asset_ids


def cleanup_unreferenced_images(cutoff):
    """Stage old unreferenced image rows for deletion and return their IDs.

    The caller must commit the database transaction before passing the returned
    IDs to ``delete_asset_files``.
    """
    referenced_asset = exists().where(
        models.RevisionImages.image_id == models.ImageAssets.id
    )
    assets = models.ImageAssets.query.filter(
        models.ImageAssets.created_at < cutoff,
        ~referenced_asset,
    ).all()
    asset_ids = [asset.id for asset in assets]
    for asset in assets:
        db.session.delete(asset)
    return asset_ids


def image_to_dict(asset):
    return {
        "id": asset.id,
        "filename": asset.original_filename,
        "width": asset.width,
        "height": asset.height,
        "thumbnail_url": url_for(
            "images.serve_image",
            image_id=asset.id,
            variant="thumbnail",
        ),
        "display_url": url_for(
            "images.serve_image",
            image_id=asset.id,
            variant="display",
        ),
        "master_url": url_for(
            "images.serve_image",
            image_id=asset.id,
            variant="master",
        ),
        "attached": asset.page_id is not None,
    }


ALLOWED_HTML_TAGS = frozenset(bleach.sanitizer.ALLOWED_TAGS).union(
    {
        "p",
        "br",
        "hr",
        "pre",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "img",
    }
)


def _allow_html_attribute(tag, name, value):
    if tag == "a":
        if name in {"href", "title"}:
            return True
        if name == "class":
            return set(value.split()).issubset(
                {"wiki-hyperlink", "unresolved-hyperlink"}
            )
        return False

    if tag == "img":
        if name == "src":
            return LOCAL_IMAGE_URL_PATTERN.fullmatch(value) is not None
        if name in {"alt", "title"}:
            return True
        if name == "loading":
            return value in {"lazy", "eager"}
        return name == "decoding" and value in {"async", "sync", "auto"}

    if tag in {"th", "td"}:
        return name in {"colspan", "rowspan"} and value.isdigit()
    return False


def sanitize_rendered_html(rendered_html):
    """Sanitize rendered Markdown and only permit local uploaded images."""
    rendered_html = DANGEROUS_HTML_BLOCK_PATTERN.sub("", rendered_html)
    sanitized_html = bleach.clean(
        rendered_html,
        tags=ALLOWED_HTML_TAGS,
        attributes=_allow_html_attribute,
        protocols={"http", "https", "mailto"},
        strip=True,
        strip_comments=True,
    )

    def enhance_image(image_match):
        image_tag = image_match.group(0)
        if " src=" not in image_tag:
            return ""
        if " loading=" not in image_tag:
            image_tag = image_tag.replace("<img", '<img loading="lazy"', 1)
        if " decoding=" not in image_tag:
            image_tag = image_tag.replace("<img", '<img decoding="async"', 1)
        return image_tag

    return IMAGE_TAG_PATTERN.sub(enhance_image, sanitized_html)
