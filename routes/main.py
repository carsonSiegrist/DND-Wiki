#For routes that don't belong elsewhere. I.e., non-auth routes.
from flask import Blueprint, render_template
from sqlalchemy import func

import models


main_bp = Blueprint("main", __name__)


@main_bp.route("/", methods=["GET"])
def index():
    return render_template("index.html")


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
