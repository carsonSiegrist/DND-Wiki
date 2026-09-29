#Construct and configure the app. 

import os

from dotenv import load_dotenv
from flask import Flask

from extensions import db, login_manager

load_dotenv()

def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")

    db.init_app(app)
    login_manager.init_app(app)

    # Import models so SQLAlchemy knows about them before create_all().
    import models

    # Blueprints: 
    from routes.main import main_bp
    from routes.auth import auth_bp
    from routes.pages import pages_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)

    with app.app_context():
        db.create_all()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)