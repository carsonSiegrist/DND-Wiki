import re
import unicodedata
from datetime import datetime, timezone
from html import escape

import markdown
from flask import abort, Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import models
from extensions import db
from forms.pages import (
    DeletePageForm,
    DeleteRevisionForm,
    PageCreateForm,
    RestoreRevisionForm,
)


pages_bp = Blueprint("pages", __name__, url_prefix="/pages")

ADMIN_ROLE = "admin"
REGULAR_PAGE_TYPES = {"article", "recap"}
WIKI_LINK_PATTERN = re.compile(r"\[\[([^\[\]\n]+)\]\]")
HISTORICAL_TITLE_ERROR = (
    "That title was previously used by a wiki page and is reserved so old "
    "links keep working. Please choose a different title."
)


def is_admin():
    return current_user.is_authenticated and current_user.role == ADMIN_ROLE


def can_edit_page(page):
    return is_admin() or page.page_type in REGULAR_PAGE_TYPES


@pages_bp.route("/id/<int:page_id>", methods=["GET"])
def view_page_by_id(page_id):
    page = db.get_or_404(models.Pages, page_id)
    return redirect(url_for("pages.view_page", slug=page.slug))


@pages_bp.route("/view/<slug>", methods=["GET"])
def view_page(slug):
    page = models.Pages.query.filter_by(slug=slug).first_or_404()
    current_revision = db.session.get(models.PageRevisions, page.current_revision_id)

    if current_revision is None:
        abort(404)

    rendered_body = render_wiki_markdown(current_revision.body_markdown)
    draft_key = None
    if current_user.is_authenticated and request.args.get("saved") == "1":
        if request.args.get("draft") == "create":
            draft_key = get_draft_key()
        elif request.args.get("draft") == "edit":
            draft_key = get_draft_key(page)

    return render_template(
        "view_page.html",
        page=page,
        rendered_body=rendered_body,
        can_edit=can_edit_page(page),
        can_delete=is_admin(),
        delete_form=DeletePageForm(),
        is_old_revision=False,
        clear_page_draft=draft_key is not None,
        draft_key=draft_key,
    )


@pages_bp.route("/view/<slug>/versions", methods=["GET"])
def page_versions(slug):
    page = models.Pages.query.filter_by(slug=slug).first_or_404()
    revision_rows = (
        db.session.query(models.PageRevisions, models.User)
        .join(models.User, models.PageRevisions.author_id == models.User.id)
        .filter(models.PageRevisions.page_id == page.id)
        .order_by(models.PageRevisions.revision_number.desc())
        .all()
    )

    return render_template(
        "page_versions.html",
        page=page,
        revision_rows=revision_rows,
    )


@pages_bp.route("/view/<slug>/versions/<int:revision_number>", methods=["GET"])
def view_revision(slug, revision_number):
    page = models.Pages.query.filter_by(slug=slug).first_or_404()
    revision = get_revision_or_404(page, revision_number)

    if revision.id == page.current_revision_id:
        return redirect(url_for("pages.view_page", slug=page.slug))

    return render_template(
        "view_page.html",
        page=page,
        revision=revision,
        rendered_body=render_wiki_markdown(revision.body_markdown),
        can_edit=can_edit_page(page),
        can_delete=is_admin(),
        is_old_revision=True,
        restore_form=RestoreRevisionForm(),
        delete_revision_form=DeleteRevisionForm(),
        clear_page_draft=False,
        draft_key=None,
    )


@pages_bp.route(
    "/view/<slug>/versions/<int:revision_number>/restore",
    methods=["POST"],
)
@login_required
def restore_revision(slug, revision_number):
    page = models.Pages.query.filter_by(slug=slug).first_or_404()
    if not can_edit_page(page):
        abort(403)

    revision = get_revision_or_404(page, revision_number)
    if revision.id == page.current_revision_id:
        abort(400)

    form = RestoreRevisionForm()
    if not form.validate_on_submit():
        abort(400)

    page.current_revision_id = revision.id
    page.updated_at = datetime.now(timezone.utc)
    refresh_page_links(page, revision.body_markdown)
    db.session.commit()

    flash(f"Version {revision.revision_number} restored.", "success")
    return redirect(url_for("pages.view_page", slug=page.slug))


@pages_bp.route(
    "/view/<slug>/versions/<int:revision_number>/delete",
    methods=["POST"],
)
@login_required
def delete_revision(slug, revision_number):
    if not is_admin():
        abort(403)

    page = models.Pages.query.filter_by(slug=slug).first_or_404()
    revision = get_revision_or_404(page, revision_number)
    if revision.id == page.current_revision_id:
        abort(400)

    form = DeleteRevisionForm()
    if not form.validate_on_submit():
        abort(400)

    db.session.delete(revision)
    db.session.commit()

    flash(f"Version {revision_number} permanently deleted.", "success")
    return redirect(url_for("pages.page_versions", slug=page.slug))


@pages_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_page():
    form = PageCreateForm()
    configure_form(form)
    prefilled_title = False

    if request.method == "GET":
        requested_title = request.args.get("title", "").strip()
        if requested_title:
            form.title.data = requested_title[:200]
            prefilled_title = True

    if not is_admin():
        form.page_type.data = "recap" if form.is_recap.data else "article"

    page_type = get_requested_page_type(form)
    clear_unused_session_number(form, page_type)

    if request.method == "GET" and form.session_number.data is None:
        form.session_number.data = get_next_session_number()

    if form.validate_on_submit():
        if page_type == "recap" and form.session_number.data is None:
            form.session_number.errors.append("Recaps require a session number!")
        elif not validate_page_title(form):
            pass
        else:
            try:
                page = create_new_page(form, page_type)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                add_integrity_error(form)
            else:
                flash("Page created successfully.", "success")
                return redirect(
                    url_for(
                        "pages.view_page",
                        slug=page.slug,
                        saved=1,
                        draft="create",
                    )
                )

    return render_page_form(
        form,
        "Create a Wiki Page",
        get_draft_key(),
        prefilled_title=prefilled_title,
    )


@pages_bp.route("/edit/<slug>", methods=["GET", "POST"])
@login_required
def edit_page(slug):
    page = models.Pages.query.filter_by(slug=slug).first_or_404()

    if not can_edit_page(page):
        abort(403)

    form = PageCreateForm()
    configure_form(form)

    if request.method == "GET":
        populate_edit_form(form, page)
    elif not is_admin():
        form.page_type.data = "recap" if form.is_recap.data else "article"

    page_type = get_requested_page_type(form)
    clear_unused_session_number(form, page_type)

    if form.validate_on_submit():
        if page_type == "recap" and form.session_number.data is None:
            form.session_number.errors.append("Recaps require a session number!")
        elif not validate_page_title(form, exclude_page_id=page.id):
            pass
        else:
            try:
                update_page(page, form, page_type)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                add_integrity_error(form)
            else:
                flash("Page updated successfully.", "success")
                return redirect(
                    url_for(
                        "pages.view_page",
                        slug=page.slug,
                        saved=1,
                        draft="edit",
                    )
                )

    form.submit.label.text = "Save Changes"
    return render_page_form(
        form,
        f"Edit {page.title}",
        get_draft_key(page),
        editing=True,
    )


@pages_bp.route("/delete/<slug>", methods=["POST"])
@login_required
def delete_page(slug):
    if not is_admin():
        abort(403)

    page = models.Pages.query.filter_by(slug=slug).first_or_404()
    form = DeletePageForm()
    if not form.validate_on_submit():
        abort(400)

    title = page.title

    reserve_page_title(page, page.title)
    models.PageTitleAliases.query.filter_by(page_id=page.id).update(
        {models.PageTitleAliases.page_id: None},
        synchronize_session=False,
    )

    models.PageLinks.query.filter_by(source_page_id=page.id).delete(
        synchronize_session=False
    )
    models.PageLinks.query.filter_by(target_page_id=page.id).update(
        {models.PageLinks.target_page_id: None},
        synchronize_session=False,
    )
    models.PageCategories.query.filter_by(page_id=page.id).delete(
        synchronize_session=False
    )

    page.current_revision_id = None
    db.session.flush()
    models.PageRevisions.query.filter_by(page_id=page.id).delete(
        synchronize_session=False
    )
    db.session.delete(page)
    db.session.commit()

    flash(f'Page "{title}" was permanently deleted.', "success")
    return redirect(url_for("main.index"))


def configure_form(form):
    categories = models.Categories.query.order_by(models.Categories.name.asc()).all()
    form.categories.choices = [
        (category.id, category.name) for category in categories
    ]


def get_revision_or_404(page, revision_number):
    return models.PageRevisions.query.filter_by(
        page_id=page.id,
        revision_number=revision_number,
    ).first_or_404()


def populate_edit_form(form, page):
    current_revision = db.session.get(models.PageRevisions, page.current_revision_id)
    if current_revision is None:
        abort(404)

    form.title.data = page.title
    form.page_type.data = page.page_type
    form.is_recap.data = page.page_type == "recap"
    form.session_number.data = page.session_number or get_next_session_number()
    form.categories.data = [
        association.category_id
        for association in models.PageCategories.query.filter_by(page_id=page.id)
    ]
    form.body_markdown.data = current_revision.body_markdown


def render_page_form(
    form,
    form_title,
    draft_key,
    editing=False,
    prefilled_title=False,
):
    return render_template(
        "create_page.html",
        form=form,
        form_title=form_title,
        draft_key=draft_key,
        editing=editing,
        prefilled_title=prefilled_title,
    )


def get_requested_page_type(form):
    if is_admin():
        return form.page_type.data
    return "recap" if form.is_recap.data else "article"


def clear_unused_session_number(form, page_type):
    if request.method == "POST" and page_type != "recap":
        form.session_number.data = None
        form.session_number.raw_data = None


def validate_page_title(form, exclude_page_id=None):
    title = form.title.data.strip()
    query = models.Pages.query.filter_by(title=title.strip())
    if exclude_page_id is not None:
        query = query.filter(models.Pages.id != exclude_page_id)
    if query.first() is not None:
        form.title.errors.append("A page with that title already exists.")
        return False

    historical_title = models.PageTitleAliases.query.filter_by(title=title).first()
    if historical_title is not None:
        form.title.errors.append(HISTORICAL_TITLE_ERROR)
        return False

    return True


def add_integrity_error(form):
    title = (form.title.data or "").strip()
    if title and models.PageTitleAliases.query.filter_by(title=title).first():
        form.title.errors.append(HISTORICAL_TITLE_ERROR)
        return

    form.title.errors.append(
        "That page or category already exists. Please choose another name."
    )


def get_draft_key(page=None):
    if page is None:
        return f"wiki-page-draft-{current_user.id}"
    return f"wiki-page-edit-draft-{current_user.id}-{page.id}"


def get_next_session_number():
    highest = (
        db.session.query(func.max(models.Pages.session_number))
        .filter(models.Pages.page_type == "recap")
        .scalar()
    )
    return (highest or 0) + 1


def slugify(value):
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "page"


def extract_wiki_link_titles(body_markdown):
    titles = []
    seen_titles = set()

    for match in WIKI_LINK_PATTERN.finditer(body_markdown):
        title = match.group(1).strip()
        if title and title not in seen_titles:
            titles.append(title)
            seen_titles.add(title)

    return titles


def resolve_wiki_link_targets(target_titles):
    targets_by_title = {}
    unresolved_titles = set(target_titles)

    if unresolved_titles:
        current_pages = models.Pages.query.filter(
            models.Pages.title.in_(unresolved_titles)
        ).all()
        for page in current_pages:
            targets_by_title[page.title] = page
            unresolved_titles.discard(page.title)

    if unresolved_titles:
        aliases = models.PageTitleAliases.query.filter(
            models.PageTitleAliases.title.in_(unresolved_titles)
        ).all()
        page_ids = {alias.page_id for alias in aliases if alias.page_id is not None}
        pages_by_id = {}
        if page_ids:
            pages_by_id = {
                page.id: page
                for page in models.Pages.query.filter(models.Pages.id.in_(page_ids))
            }

        for alias in aliases:
            targets_by_title[alias.title] = pages_by_id.get(alias.page_id)

    return targets_by_title


def render_wiki_markdown(body_markdown):
    target_titles = extract_wiki_link_titles(body_markdown)
    pages_by_title = resolve_wiki_link_targets(target_titles)

    def replace_wiki_link(match):
        target_title = match.group(1).strip()
        if not target_title:
            return match.group(0)

        target_page = pages_by_title.get(target_title)
        if target_page is None:
            link_class = "unresolved-hyperlink"
            href = url_for("pages.create_page", title=target_title)
        else:
            link_class = "wiki-hyperlink"
            href = url_for("pages.view_page_by_id", page_id=target_page.id)

        return (
            f'<a class="{link_class}" href="{escape(href, quote=True)}">'
            f"{escape(target_title)}</a>"
        )

    linked_markdown = WIKI_LINK_PATTERN.sub(replace_wiki_link, body_markdown)
    return markdown.markdown(linked_markdown)


def refresh_page_links(page, body_markdown):
    target_titles = extract_wiki_link_titles(body_markdown)
    pages_by_title = resolve_wiki_link_targets(target_titles)

    models.PageLinks.query.filter_by(source_page_id=page.id).delete(
        synchronize_session=False
    )

    linked_page_ids = set()
    for target_title in target_titles:
        target_page = pages_by_title.get(target_title)
        if target_page is not None:
            if target_page.id in linked_page_ids:
                continue
            linked_page_ids.add(target_page.id)

        db.session.add(
            models.PageLinks(
                source_page_id=page.id,
                target_page_id=target_page.id if target_page else None,
                target_title=target_title,
            )
        )


def resolve_incoming_page_links(page):
    recognized_titles = [page.title]
    recognized_titles.extend(
        alias.title
        for alias in models.PageTitleAliases.query.filter_by(page_id=page.id)
    )

    existing_links = models.PageLinks.query.filter_by(
        target_page_id=page.id
    ).order_by(models.PageLinks.id).all()
    kept_link_by_source = {}
    for link in existing_links:
        if link.source_page_id in kept_link_by_source:
            db.session.delete(link)
        else:
            kept_link_by_source[link.source_page_id] = link

    candidate_links = models.PageLinks.query.filter(
        models.PageLinks.target_title.in_(recognized_titles)
    ).order_by(models.PageLinks.id).all()
    for link in candidate_links:
        kept_link = kept_link_by_source.get(link.source_page_id)
        if kept_link is not None and kept_link.id != link.id:
            db.session.delete(link)
        else:
            link.target_page_id = page.id
            kept_link_by_source[link.source_page_id] = link


def reserve_page_title(page, title):
    existing_alias = models.PageTitleAliases.query.filter_by(title=title).first()
    if existing_alias is None:
        db.session.add(
            models.PageTitleAliases(
                page_id=page.id,
                title=title,
            )
        )
        db.session.flush()


def get_available_slug(title, model, exclude_id=None):
    base_slug = slugify(title)
    slug = base_slug
    suffix = 2

    while True:
        query = model.query.filter_by(slug=slug)
        if exclude_id is not None:
            query = query.filter(model.id != exclude_id)
        if query.first() is None:
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1


def get_category_ids(form):
    category_ids = set(form.categories.data)
    new_category_names = {}

    for value in form.new_categories.data:
        name = (value or "").strip()
        if name:
            new_category_names.setdefault(name.lower(), name)

    for new_category_name in new_category_names.values():
        category = models.Categories.query.filter(
            func.lower(models.Categories.name) == new_category_name.lower()
        ).first()

        if category is None:
            category = models.Categories(
                name=new_category_name,
                slug=get_available_slug(new_category_name, models.Categories),
                created_by=current_user.id,
            )
            db.session.add(category)
            db.session.flush()

        category_ids.add(category.id)

    return category_ids


def set_page_categories(page, form):
    models.PageCategories.query.filter_by(page_id=page.id).delete(
        synchronize_session=False
    )

    for category_id in get_category_ids(form):
        db.session.add(
            models.PageCategories(
                page_id=page.id,
                category_id=category_id,
            )
        )


def create_new_page(form, page_type):
    title = form.title.data.strip()
    page = models.Pages(
        title=title,
        slug=get_available_slug(title, models.Pages),
        page_type=page_type,
        created_by=current_user.id,
        session_number=form.session_number.data if page_type == "recap" else None,
    )
    db.session.add(page)
    db.session.flush()

    revision = models.PageRevisions(
        page_id=page.id,
        author_id=current_user.id,
        body_markdown=form.body_markdown.data,
        edit_summary="Initial revision.",
        revision_number=1,
    )
    db.session.add(revision)
    db.session.flush()
    page.current_revision_id = revision.id
    set_page_categories(page, form)
    refresh_page_links(page, revision.body_markdown)
    resolve_incoming_page_links(page)

    return page


def update_page(page, form, page_type):
    old_title = page.title
    title = form.title.data.strip()
    page.title = title
    page.slug = get_available_slug(title, models.Pages, exclude_id=page.id)
    page.page_type = page_type
    page.session_number = form.session_number.data if page_type == "recap" else None
    page.updated_at = datetime.now(timezone.utc)

    highest_revision = (
        db.session.query(func.max(models.PageRevisions.revision_number))
        .filter(models.PageRevisions.page_id == page.id)
        .scalar()
    )
    revision = models.PageRevisions(
        page_id=page.id,
        author_id=current_user.id,
        body_markdown=form.body_markdown.data,
        edit_summary=(form.edit_summary.data or "").strip() or None,
        revision_number=(highest_revision or 0) + 1,
    )
    db.session.add(revision)
    db.session.flush()
    page.current_revision_id = revision.id
    set_page_categories(page, form)
    if old_title != page.title:
        reserve_page_title(page, old_title)
    refresh_page_links(page, revision.body_markdown)
    resolve_incoming_page_links(page)
