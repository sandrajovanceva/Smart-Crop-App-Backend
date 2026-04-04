from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from app.config import Config

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app)
    db.init_app(app)

    from app.routes.advisor import advisor_bp
    app.register_blueprint(advisor_bp, url_prefix='/api/advisor')

    with app.app_context():
        from app.models.User import User
        from app.models.Field import Field
        from app.models.Crop_analysis import CropAnalysis
        from app.models.Weather_data import WeatherData
        from app.models.Report import Report
        db.create_all()

    return app