from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flasgger import Swagger
from app.config import Config
from app.errors import error_response, register_error_handlers
from app.logging_config import configure_logging, register_request_logging

db = SQLAlchemy()
bcrypt = Bcrypt()
jwt = JWTManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    configure_logging(app)

    app.config['SWAGGER'] = {
        'title': 'Smart Crops API',
        'uiversion': 3,
        'version': '1.0.0',
        'description': 'API документација за Smart Crops Backend',
        'securityDefinitions': {
            'BearerAuth': {
                'type': 'apiKey',
                'name': 'Authorization',
                'in': 'header',
                'description': 'Внеси: Bearer <JWT token>'
            }
        },
        'security': [{'BearerAuth': []}]
    }

    CORS(app)
    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    Swagger(app)
    register_request_logging(app)
    register_error_handlers(app)

    from app.routes.advisor import advisor_bp
    from app.routes.auth import auth_bp
    from app.routes.fields import fields_bp
    from app.routes.weather import weather_bp

    app.register_blueprint(advisor_bp, url_prefix='/api/advisor')
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(fields_bp, url_prefix='/api/fields')
    app.register_blueprint(weather_bp, url_prefix='/api/weather')

    from .models import TokenBlocklist

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        jti = jwt_payload["jti"]
        token = TokenBlocklist.query.filter_by(jti=jti).first()
        return token is not None

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return error_response("Token has expired", 401, "token_expired")

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return error_response("Invalid token", 401, "invalid_token")

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return error_response("Authorization token is required", 401, "authorization_required")

    with app.app_context():
        from app.models.User import User
        from app.models.TokenBlocklist import TokenBlocklist
        from app.models.Field import Field
        from app.models.Crop_analysis import CropAnalysis
        from app.models.Weather_data import WeatherData
        from app.models.Report import Report
        from app.models.AdviceCache import AdviceCache
        db.create_all()

    return app
