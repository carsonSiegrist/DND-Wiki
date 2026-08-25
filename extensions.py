# Manage extensions so that they can be imported as necessary 
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()

login_manager = LoginManager()
login_manager.login_view = "auth.login"