import os

from flasgger import Swagger
from flask import Flask
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy

from app.config import Config
from app.errors import error_response, register_error_handlers
from app.logging_config import configure_logging, register_request_logging

db = SQLAlchemy()
bcrypt = Bcrypt()
jwt = JWTManager()


def _build_cors_origins():
    defaults = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

    extra = os.getenv("CORS_ORIGINS", "")
    extras = [o.strip() for o in extra.split(",") if o.strip()]

    return defaults + extras


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.url_map.strict_slashes = False
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

    cors_origins = _build_cors_origins()
    cors_regex = [
        r"https://.*\.vercel\.app",
    ]
    CORS(
        app,
        resources={r"/api/*": {"origins": cors_origins + cors_regex}},
        supports_credentials=True,
        expose_headers=["Authorization", "Content-Disposition"],
        allow_headers=["Authorization", "Content-Type"],
    )

    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    Swagger(app)
    register_request_logging(app)
    register_error_handlers(app)

    from app.routes.auth import auth_bp
    from app.routes.fields import fields_bp
    from app.routes.weather import weather_bp
    from app.routes.reports import reports_bp
    from app.routes.diseases import diseases_bp
    from app.routes.fertilizer import fertilizer_bp
    from app.routes.crop_analysis import crop_analysis_bp

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(fields_bp, url_prefix='/api/fields')
    app.register_blueprint(weather_bp, url_prefix='/api/weather')
    app.register_blueprint(reports_bp, url_prefix='/api/reports')
    app.register_blueprint(diseases_bp, url_prefix='/api/diseases')
    app.register_blueprint(fertilizer_bp, url_prefix='/api/fertilizer')
    app.register_blueprint(crop_analysis_bp, url_prefix='/api/crop-analysis')

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
