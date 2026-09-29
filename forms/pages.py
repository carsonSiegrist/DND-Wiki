#For wiki page CRUD.
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    BooleanField,
    IntegerField,
    SelectMultipleField,
    TextAreaField,
    SubmitField,
)
from wtforms.validators import DataRequired, Length, Optional, NumberRange


class PageCreateForm(FlaskForm):
    title = StringField(
        "Title",
        validators=[DataRequired(), Length(max=200)],
    )

    is_recap = BooleanField("Session recap")

    session_number = IntegerField(
        "Session Number",
        validators=[
            Optional(),
            NumberRange(min=1),
        ],
    )

    categories = SelectMultipleField(
        "Categories",
        coerce=int,
        validators=[Optional()],
    )

    new_category = StringField(
        "New Category",
        validators=[Optional(), Length(max=100)],
    )

    body_markdown = TextAreaField(
        "Page",
        validators=[DataRequired()],
    )

    submit = SubmitField("Create Page")
