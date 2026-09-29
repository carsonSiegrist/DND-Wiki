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
from wtforms.validators import DataRequired, Optional, NumberRange


class PageCreateForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired()])

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

    body_markdown = TextAreaField(
        "Page",
        validators=[DataRequired()],
    )

    submit = SubmitField("Create Page")