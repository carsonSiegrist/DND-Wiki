from flask import Blueprint, render_template, redirect, url_for, flash
from sqlalchemy.exc import IntegrityError
from flask_login import login_user, logout_user, login_required, current_user

import models
from extensions import db, login_manager
from forms.auth import RegisterForm, LoginForm


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
     # If the user is already logged in, send them away
    if current_user.is_authenticated:
        flash("You are already logged in.", "error")
        return redirect(url_for("main.index"))


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
            flash("Registration Successful! Please log in!", "success")
            return redirect(url_for("auth.login"))

    return render_template(
        "auth/register.html",
        form=form,
    )

@auth_bp.route("/login", methods=["GET", "POST"])
def login():

     # If the user is already logged in, send them away
    if current_user.is_authenticated:
        flash("You are already logged in.", "error")
        return redirect(url_for("main.index"))

    form = LoginForm()

    if form.validate_on_submit():
        user = models.User.query.filter_by(username=form.username.data).first()
        
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for("main.index")) 
        
        flash("Invalid username or password, please try again.", "error") 

    return render_template(
        "auth/login.html",
        form=form,
    )

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("User logged out successfully.", "success")
    return redirect(url_for("main.index"))