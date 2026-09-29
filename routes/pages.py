import re
import unicodedata

import markdown
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import models
from extensions import db

from forms.pages import PageCreateForm



pages_bp = Blueprint("pages", __name__, url_prefix="/pages")

@pages_bp.route("/view/<slug>", methods=["GET"]) 
def view_page(slug):
    #Get page by slug, and get the current revision of that page
    #TODO: Add error handling for page not found, and for page with no revisions
    page = models.Pages.query.filter_by(slug=slug).first_or_404()
    current_revision = db.session.get(models.PageRevisions, page.current_revision_id)
    
    rendered_body=markdown.markdown(current_revision.body_markdown)

    return render_template(
        "view_page.html",
        page=page,
        rendered_body=rendered_body,
        clear_page_draft=request.args.get("created") == "1",
    )

@pages_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_page():
    form = PageCreateForm()

    categories = (
        models.Categories.query.order_by(models.Categories.name.asc()).all()
    )

    form.categories.choices = [
        (category.id, category.name) for category in categories 
    ]

    # A previously entered recap number should not block an ordinary article.
    if request.method == "POST" and not form.is_recap.data:
        form.session_number.data = None
        form.session_number.raw_data = None

    if request.method == "GET" and form.session_number.data is None:
        form.session_number.data = get_next_session_number() 

    if form.validate_on_submit():
        if form.is_recap.data and form.session_number.data is None:
            form.session_number.errors.append("Recaps require a session number!")
        elif models.Pages.query.filter_by(title=form.title.data.strip()).first():
            form.title.errors.append("A page with that title already exists.")
        else:
            try:
                page = create_new_page(form)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.title.errors.append(
                    "That page or category already exists. Please choose another name."
                )
            else:
                flash("Page created successfully.", "success")
                return redirect(
                    url_for("pages.view_page", slug=page.slug, created=1)
                )

    return render_template("create_page.html", form=form)


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


def get_available_slug(title, model):
    base_slug = slugify(title)
    slug = base_slug
    suffix = 2

    while model.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    return slug


def create_new_page(form):
    title = form.title.data.strip()
    page = models.Pages(
        title=title,
        slug=get_available_slug(title, models.Pages),
        page_type="recap" if form.is_recap.data else "article",
        created_by=current_user.id,
        session_number=form.session_number.data if form.is_recap.data else None,
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

    category_ids = set(form.categories.data)
    new_category_name = (form.new_category.data or "").strip()

    if new_category_name:
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

    for category_id in category_ids:
        db.session.add(
            models.PageCategories(
                page_id=page.id,
                category_id=category_id,
            )
        )

    return page
