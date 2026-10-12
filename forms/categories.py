from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length


class RenameCategoryForm(FlaskForm):
    name = StringField(
        "Category Name",
        validators=[DataRequired(), Length(max=100)],
    )
    submit = SubmitField("Rename Category")


class DeleteCategoryForm(FlaskForm):
    submit = SubmitField("Permanently Delete Category")
