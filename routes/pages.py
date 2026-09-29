import markdown
from flask import Blueprint, render_template
from flask_login import login_required, current_user


import models
from sqlalchemy import func

from forms.pages import PageCreateForm



pages_bp = Blueprint("pages", __name__, url_prefix="/pages")

@pages_bp.route("/view/<slug>", methods=["GET"]) 
def view_page(slug):
    #Get page by slug, and get the current revision of that page
    #TODO: Add error handling for page not found, and for page with no revisions
    page = models.Pages.query.filter_by(slug=slug).first_or_404()
    current_revision = models.PageRevisions.query.filter_by(page_id=page.id, revision_number=page.current_revision_id).first()
    
    rendered_body=markdown.markdown(current_revision.body_markdown)

    return render_template("view_page.html", page=page, rendered_body=rendered_body)

@pages_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_page():
    form = PageCreateForm()

    caregories = (
        models.Categories.query.order_by(Categories.name.asc()).all()
    )

    form.categories.choices = [
        (category.id, category.name) for category in categories 
    ]

    if request.method == "GET":
        form.session_number.data = get_next_session_number() 

    if form.validate_on_submit:
        if form.is_recap.data and form.session_number.data is None:
            form.session_number.errors.append("Recaps require a session number!")
            return render_template("pages/create.html", form=form)
        
        page = create_new_page(form) 

        return redirect(url_for("view_page", slug=page.slug))
    
    return render_template("pages/create.html", form=form)


def get_next_session_number():
    highest = (
        db.session.query(func.max(Pages.session_number))
        .filter(Page.page_type=="recap")
        .scalar()
    )

    return (highest or 0) + 1

def create_new_page(page): #TODO! Implement
    pass