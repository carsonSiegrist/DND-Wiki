# /routes/auth.py

from flask import Blueprint, render_template
from werkzeug.security import generate_password_hash

import models
from extensions import db, login_manager
from forms.auth import RegisterForm


auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth",
)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(models.User, int(user_id))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()

    if form.validate_on_submit():
        user = models.User(
            username = form.username.data,
            email = form.email.data
        )

        user.set_password(form.password.data)

        db.session.add(user)

        #Form validates data; could be a race though so catch db error
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.username.errors.append("Username or email is already in use.")
        else:
            #TODO: Pass some message to login to indicate that account was successfully registered. 
            return redirect(url_for("auth.login"))

    return render_template(
        "auth/register.html",
        form=form,
    )

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    return "Login page is a WIP!"