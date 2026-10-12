# Manage extensions so that they can be imported as necessary 
from flask_login import LoginManager, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


def rate_limit_key():
    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()


db = SQLAlchemy()
migrate = Migrate()
limiter = Limiter(key_func=rate_limit_key)

login_manager = LoginManager()
login_manager.login_view = "auth.login"
