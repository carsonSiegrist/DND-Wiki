from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError
import models

class RegisterForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(message="A username is required.")
            ],
    )

    email = StringField(
        "Email",
        validators=[
            DataRequired(message="An email address is required."),
            Email(message="Please provide a valid email address.")
            ],
    )

    password = PasswordField(
        "Password",
        validators=[
            DataRequired(message="Password is required."),
            Length(min=10, message="Password must be at least 10 characters long.")
        ],
    )

    password_check = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(message="Password confirmation is required."),
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

class LoginForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(message="Please enter a username!")
            ],
    )

    password = PasswordField(
        "Password",
        validators=[
            DataRequired(message="Please enter a password!"),
        ],
    )


    submit = SubmitField("Submit")