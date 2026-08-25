from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo
import markdown
import os

app = Flask(__name__)
login_manager = LoginManager()
db = SQLAlchemy()

app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")

db.init_app(app)
login_manager.init_app(app)

import models 


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", pages=models.Pages.query.all())

@app.route("/page/<slug>", methods=["GET"]) 
def view_page(slug):
    #Get page by slug, and get the current revision of that page
    #TODO: Add error handling for page not found, and for page with no revisions
    page = models.Pages.query.filter_by(slug=slug).first_or_404()
    current_revision = models.PageRevisions.query.filter_by(page_id=page.id, revision_number=page.current_revision_id).first()
    
    rendered_body=markdown.markdown(current_revision.body_markdown)

    return render_template("view_page.html", page=page, rendered_body=rendered_body)

#----REGISTRATION----
@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    email = StringField("Email", validators=[Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    password_check = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo("password", message="Passwords must match.")])
    submit = SubmitField("Submit")
    

@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data
        email = form.email.data
        password = form.password.data
        
        print(username, email, password)
        return "Success!"

    #TODO: Maket this elegant. Display errors to user, send them back to the form. 
    elif request.method=="POST":
        print("failed validation")
        return "fail"

    else:
        return render_template("auth/register.html", form=form)




with app.app_context():
    db.create_all()