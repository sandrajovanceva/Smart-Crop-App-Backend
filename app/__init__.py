from flask import Flask
from flask_cors import CORS
# from flas_sqlalchemy import SQLAlchemy
from app.config import Config

# db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app)
    # db.init_app(app)

    from app.routes.advisor import advisor_bp
    app.register_blueprint(advisor_bp, url_prefix='/api/advisor')

    # with app.app_context():
        # db.create_all()

    return app