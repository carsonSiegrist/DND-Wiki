from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError
import models


class RegisterForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired()
            ],
    )

    email = StringField(
        "Email",
        validators=[
            DataRequired(),
            Email()
            ],
    )

    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=10)
        ],
    )

    password_check = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(),
            EqualTo("password", message="Passwords must match."),
        ],
    )

    submit = SubmitField("Submit")

    #Custom validators automatically discovered. 
    def validate_username(self, field):
        existing_user = models.User.query.filter_by(
            username=field.data
        ).first()

        if existing_user:
            raise ValidationError("That username is already in use.")

    def validate_email(self, field):
        existing_user = models.User.query.filter_by(
            email=field.data
        ).first()

        if existing_user:
            raise ValidationError("That email is already registered.")