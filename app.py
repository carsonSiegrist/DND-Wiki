from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
import markdown

db = SQLAlchemy()

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///dndwiki.db'

db.init_app(app)

import models 


@app.route("/")
def index():
    return render_template("index.html", pages=models.Pages.query.all())

#TODO: Change to slugs instead of id 
@app.route("/page/<int:page_id>")
def view_page(page_id):
    #Get page by ID, and get the current revision of that page
    #TODO: Add error handling for page not found, and for page with no revisions
    page = models.Pages.query.get_or_404(page_id)
    current_revision = models.PageRevisions.query.filter_by(page_id=page.id, revision_number=page.current_revision_id).first()
    
    rendered_body=markdown.markdown(current_revision.body_markdown)

    return render_template("view_page.html", page=page, rendered_body=rendered_body)

with app.app_context():
    db.create_all()