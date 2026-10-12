#For routes that don't belong elsewhere. I.e., non-auth routes.
import math
import re
import unicodedata

from flask import abort, Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import models
from extensions import db, limiter
from forms.categories import DeleteCategoryForm, RenameCategoryForm
from search import SEARCH_QUERY_LIMIT, SEARCH_RESULT_LIMIT, search_pages


main_bp = Blueprint("main", __name__)
ADMIN_ROLE = "admin"


def is_admin():
    return current_user.is_authenticated and current_user.role == ADMIN_ROLE


@main_bp.route("/", methods=["GET"])
def index():
    most_wanted_rows = (
        db.session.query(
            models.PageLinks.target_title,
            func.count(func.distinct(models.PageLinks.source_page_id)).label(
                "unique_reference_count"
            ),
        )
        .filter(models.PageLinks.target_page_id.is_(None))
        .group_by(models.PageLinks.target_title)
        .order_by(
            func.count(func.distinct(models.PageLinks.source_page_id)).desc(),
            func.lower(models.PageLinks.target_title).asc(),
        )
        .all()
    )
    recent_revision_rows = (
        db.session.query(
            models.PageRevisions,
            models.Pages,
            models.User,
            models.PageRevisionTitles.title,
        )
        .join(models.Pages, models.PageRevisions.page_id == models.Pages.id)
        .join(models.User, models.PageRevisions.author_id == models.User.id)
        .outerjoin(
            models.PageRevisionTitles,
            models.PageRevisionTitles.revision_id == models.PageRevisions.id,
        )
        .order_by(
            models.PageRevisions.created_at.desc(),
            models.PageRevisions.id.desc(),
        )
        .limit(10)
        .all()
    )

    return render_template(
        "index.html",
        most_wanted_rows=most_wanted_rows,
        recent_revision_rows=recent_revision_rows,
    )


@main_bp.route("/search", methods=["GET"])
@limiter.limit("120 per minute")
def search():
    query = request.args.get("q", "").strip()[:SEARCH_QUERY_LIMIT]
    requested_page = max(request.args.get("page", 1, type=int), 1)
    all_results = search_pages(query) if query else []
    result_count = len(all_results)
    page_count = math.ceil(result_count / SEARCH_RESULT_LIMIT)
    if page_count:
        requested_page = min(requested_page, page_count)
    start = (requested_page - 1) * SEARCH_RESULT_LIMIT
    results = all_results[start : start + SEARCH_RESULT_LIMIT]

    return render_template(
        "search_results.html",
        query=query,
        results=results,
        result_count=result_count,
        current_page=requested_page,
        page_count=page_count,
    )


@main_bp.route("/pages", methods=["GET"])
def all_pages():
    official_pages = (
        models.Pages.query.filter_by(page_type="official")
        .order_by(func.lower(models.Pages.title).asc())
        .all()
    )
    recaps = (
        models.Pages.query.filter_by(page_type="recap")
        .order_by(
            models.Pages.session_number.asc(),
            func.lower(models.Pages.title).asc(),
        )
        .all()
    )
    articles = (
        models.Pages.query.filter_by(page_type="article")
        .order_by(func.lower(models.Pages.title).asc())
        .all()
    )
    categories_by_page = get_categories_by_page(recaps + articles)

    return render_template(
        "all_pages.html",
        official_pages=official_pages,
        recap_rows=[(page, categories_by_page.get(page.id, [])) for page in recaps],
        article_rows=[
            (page, categories_by_page.get(page.id, [])) for page in articles
        ],
    )


@main_bp.route("/categories", methods=["GET"])
def categories():
    category_rows = (
        models.Categories.query.outerjoin(
            models.PageCategories,
            models.Categories.id == models.PageCategories.category_id,
        )
        .with_entities(
            models.Categories,
            func.count(models.PageCategories.page_id),
        )
        .group_by(models.Categories.id)
        .order_by(func.lower(models.Categories.name).asc())
        .all()
    )

    return render_template("categories.html", category_rows=category_rows)


@main_bp.route("/categories/<slug>", methods=["GET"])
def view_category(slug):
    category = models.Categories.query.filter_by(slug=slug).first_or_404()
    pages = (
        models.Pages.query.join(
            models.PageCategories,
            models.Pages.id == models.PageCategories.page_id,
        )
        .filter(models.PageCategories.category_id == category.id)
        .order_by(func.lower(models.Pages.title).asc())
        .all()
    )
    categories_by_page = get_categories_by_page(pages)
    page_rows = [
        (
            page,
            [
                page_category
                for page_category in categories_by_page.get(page.id, [])
                if page_category.id != category.id
            ],
        )
        for page in pages
    ]

    return render_template(
        "category.html",
        category=category,
        page_rows=page_rows,
        can_manage_category=is_admin(),
        rename_form=(
            RenameCategoryForm(data={"name": category.name})
            if is_admin()
            else None
        ),
        delete_form=DeleteCategoryForm() if is_admin() else None,
    )


@main_bp.route("/categories/<slug>/rename", methods=["POST"])
@login_required
def rename_category(slug):
    if not is_admin():
        abort(403)

    category = models.Categories.query.filter_by(slug=slug).first_or_404()
    form = RenameCategoryForm()
    if not form.validate_on_submit():
        flash("Enter a category name no longer than 100 characters.", "error")
        return redirect(url_for("main.view_category", slug=category.slug))

    new_name = form.name.data.strip()
    existing_category = models.Categories.query.filter(
        func.lower(models.Categories.name) == new_name.lower(),
        models.Categories.id != category.id,
    ).first()
    if existing_category is not None:
        flash(f'A category named "{new_name}" already exists.', "error")
        return redirect(url_for("main.view_category", slug=category.slug))

    old_name = category.name
    category.name = new_name
    category.slug = get_available_category_slug(new_name, category.id)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("That category name or address is already in use.", "error")
        return redirect(url_for("main.view_category", slug=slug))

    flash(f'Category "{old_name}" renamed to "{new_name}".', "success")
    return redirect(url_for("main.view_category", slug=category.slug))


@main_bp.route("/categories/<slug>/delete", methods=["POST"])
@login_required
def delete_category(slug):
    if not is_admin():
        abort(403)

    category = models.Categories.query.filter_by(slug=slug).first_or_404()
    form = DeleteCategoryForm()
    if not form.validate_on_submit():
        abort(400)

    category_name = category.name
    models.PageRevisionCategories.query.filter_by(category_id=category.id).update(
        {models.PageRevisionCategories.category_id: None},
        synchronize_session=False,
    )
    models.PageCategories.query.filter_by(category_id=category.id).delete(
        synchronize_session=False
    )
    db.session.delete(category)
    db.session.commit()

    flash(
        f'Category "{category_name}" was permanently deleted. Its pages were kept.',
        "success",
    )
    return redirect(url_for("main.categories"))


def get_categories_by_page(pages):
    page_ids = [page.id for page in pages]
    categories_by_page = {page_id: [] for page_id in page_ids}
    if not page_ids:
        return categories_by_page

    category_rows = (
        models.PageCategories.query.join(
            models.Categories,
            models.PageCategories.category_id == models.Categories.id,
        )
        .filter(models.PageCategories.page_id.in_(page_ids))
        .with_entities(models.PageCategories.page_id, models.Categories)
        .order_by(
            models.PageCategories.page_id.asc(),
            func.lower(models.Categories.name).asc(),
        )
        .all()
    )
    for page_id, category in category_rows:
        categories_by_page[page_id].append(category)

    return categories_by_page


def get_available_category_slug(name, exclude_category_id=None):
    normalized_name = unicodedata.normalize("NFKD", name)
    base_slug = normalized_name.encode("ascii", "ignore").decode("ascii").lower()
    base_slug = re.sub(r"[^a-z0-9]+", "-", base_slug).strip("-") or "category"
    slug = base_slug
    suffix = 2

    while True:
        query = models.Categories.query.filter_by(slug=slug)
        if exclude_category_id is not None:
            query = query.filter(models.Categories.id != exclude_category_id)
        if query.first() is None:
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1
