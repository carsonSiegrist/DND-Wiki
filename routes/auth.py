from datetime import datetime, timezone

from flask import Blueprint, flash, make_response, redirect, render_template, url_for
from sqlalchemy.exc import IntegrityError
from flask_login import login_user, logout_user, login_required, current_user

import models
from extensions import db, limiter, login_manager
from forms.auth import LoginForm, RegisterForm, ResetPasswordForm
from invites import hash_invite_key
from password_resets import hash_reset_token


auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth",
)


@login_manager.user_loader
def load_user(session_identity):
    try:
        user_id, session_version = session_identity.rsplit(":", 1)
        user_id = int(user_id)
        session_version = int(session_version)
    except (AttributeError, TypeError, ValueError):
        return None

    user = db.session.get(models.User, user_id)
    if user is None or user.session_version != session_version:
        return None
    return user


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def register():
     # If the user is already logged in, send them away
    if current_user.is_authenticated:
        flash("You are already logged in.", "error")
        return redirect(url_for("main.index"))


    form = RegisterForm()

    if form.validate_on_submit():
        invite = models.InviteKeys.query.filter_by(
            key_hash=hash_invite_key(form.invite_key.data),
            used_at=None,
        ).first()
        if invite is None:
            form.invite_key.errors.append(
                "That invite key is invalid or has already been used."
            )
        else:
            user = models.User(
                username=form.username.data,
                email=form.email.data,
            )
            user.set_password(form.password.data)
            db.session.add(user)

            try:
                db.session.flush()
                claimed_invite = models.InviteKeys.query.filter_by(
                    id=invite.id,
                    used_at=None,
                ).update(
                    {
                        models.InviteKeys.used_at: datetime.now(timezone.utc),
                        models.InviteKeys.used_by: user.id,
                    },
                    synchronize_session=False,
                )
                if claimed_invite != 1:
                    db.session.rollback()
                    form.invite_key.errors.append(
                        "That invite key has already been used."
                    )
                else:
                    db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.username.errors.append(
                    "Username or email is already in use."
                )
            else:
                if claimed_invite == 1:
                    flash("Registration Successful! Please log in!", "success")
                    return redirect(url_for("auth.login"))

    return render_template(
        "auth/register.html",
        form=form,
    )

@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("50 per hour", methods=["POST"])
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


@auth_bp.route("/reset-password/<reset_token>", methods=["GET", "POST"])
@limiter.limit("20 per hour")
@limiter.limit("5 per hour", methods=["POST"])
def reset_password(reset_token):
    now = datetime.now(timezone.utc)
    reset_record = models.PasswordResetTokens.query.filter(
        models.PasswordResetTokens.token_hash == hash_reset_token(reset_token),
        models.PasswordResetTokens.used_at.is_(None),
        models.PasswordResetTokens.expires_at > now,
    ).first()
    form = ResetPasswordForm()

    if reset_record is not None and form.validate_on_submit():
        user = db.session.get(models.User, reset_record.user_id)
        if user is None:
            reset_record = None
        else:
            user.set_password(form.password.data)
            user.session_version += 1
            claimed_reset = models.PasswordResetTokens.query.filter(
                models.PasswordResetTokens.id == reset_record.id,
                models.PasswordResetTokens.used_at.is_(None),
                models.PasswordResetTokens.expires_at > now,
            ).update(
                {models.PasswordResetTokens.used_at: now},
                synchronize_session=False,
            )
            if claimed_reset == 1:
                db.session.commit()
                logout_user()
                flash(
                    "Password updated. Please log in with your new password.",
                    "success",
                )
                return redirect(url_for("auth.login"))

            db.session.rollback()
            reset_record = None

    response = make_response(
        render_template(
            "auth/reset_password.html",
            form=form,
            reset_is_valid=reset_record is not None,
        )
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("User logged out successfully.", "success")
    return redirect(url_for("main.index"))
