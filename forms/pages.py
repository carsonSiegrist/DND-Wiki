#For wiki page CRUD.
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    FieldList,
    IntegerField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional, NumberRange


class PageCreateForm(FlaskForm):
    title = StringField(
        "Title",
        validators=[DataRequired(), Length(max=200)],
    )

    is_recap = BooleanField("Session recap")

    page_type = SelectField(
        "Page Type",
        choices=[
            ("article", "Article"),
            ("recap", "Recap"),
            ("official", "Official"),
        ],
        validators=[DataRequired()],
        default="article",
    )

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

    new_categories = FieldList(
        StringField(
            "New Category",
            validators=[Optional(), Length(max=100)],
        ),
        min_entries=0,
    )

    body_markdown = TextAreaField(
        "Page",
        validators=[DataRequired()],
    )

    edit_summary = StringField(
        "Edit Summary",
        validators=[Optional(), Length(max=512)],
    )

    submit = SubmitField("Create Page")


class DeletePageForm(FlaskForm):
    submit = SubmitField("Permanently Delete Page")


class RestoreRevisionForm(FlaskForm):
    submit = SubmitField("Restore Version")


class DeleteRevisionForm(FlaskForm):
    submit = SubmitField("Permanently Delete Revision")
