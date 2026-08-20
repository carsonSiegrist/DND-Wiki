from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///dndwiki.db'

db.init_app(app)

import models 


@app.route("/")
def home_page():
    return "<p>Hello, World!</p>"



with app.app_context():
    db.create_all()