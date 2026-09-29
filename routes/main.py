#For routes that don't belong elsewhere. I.e., non-auth routes. 
import markdown
from flask import Blueprint, render_template

import models


main_bp = Blueprint("main", __name__)


@main_bp.route("/", methods=["GET"])
def index():
    return render_template("index.html", pages=models.Pages.query.all())


# @main_bp.route("/page/<slug>", methods=["GET"]) 
# def view_page(slug):
#     #Get page by slug, and get the current revision of that page
#     #TODO: Add error handling for page not found, and for page with no revisions
#     page = models.Pages.query.filter_by(slug=slug).first_or_404()
#     current_revision = models.PageRevisions.query.filter_by(page_id=page.id, revision_number=page.current_revision_id).first()
    
#     rendered_body=markdown.markdown(current_revision.body_markdown)

#     return render_template("view_page.html", page=page, rendered_body=rendered_body)

