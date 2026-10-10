#For routes that don't belong elsewhere. I.e., non-auth routes.
import math

from flask import Blueprint, render_template, request
from sqlalchemy import func

import models
from extensions import db
from search import SEARCH_QUERY_LIMIT, SEARCH_RESULT_LIMIT, search_pages


main_bp = Blueprint("main", __name__)


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
    recaps = (
        models.Pages.query.filter_by(page_type="recap")
        .order_by(
            models.Pages.session_number.asc(),
            func.lower(models.Pages.title).asc(),
        )
        .all()
    )
    articles = (
        models.Pages.query.filter(models.Pages.page_type != "recap")
        .order_by(func.lower(models.Pages.title).asc())
        .all()
    )
    categories_by_page = get_categories_by_page(recaps + articles)

    return render_template(
        "all_pages.html",
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
    )


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
