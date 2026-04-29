from flask import g, has_request_context, jsonify
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "Internal server error"

    def __init__(self, message=None, status_code=None, code=None, details=None):
        self.message = message or self.message
        self.status_code = status_code or self.status_code
        self.code = code or self.code
        self.details = details
        super().__init__(self.message)


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"
    message = "Bad request"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Unauthorized"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Resource conflict"


class ExternalServiceError(AppError):
    status_code = 502
    code = "external_service_error"
    message = "External service error"


class ConfigurationError(AppError):
    status_code = 500
    code = "configuration_error"
    message = "Server configuration error"


def error_response(message, status_code=400, code="error", details=None):
    payload = {
        "success": False,
        "error": message,
        "code": code,
    }

    if has_request_context() and getattr(g, "request_id", None):
        payload["request_id"] = g.request_id

    if details is not None:
        payload["details"] = details

    return jsonify(payload), status_code


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(error):
        if error.status_code >= 500:
            app.logger.exception(error.message)

        return error_response(
            error.message,
            status_code=error.status_code,
            code=error.code,
            details=error.details
        )

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(error):
        from app import db

        db.session.rollback()
        app.logger.exception("Database error")
        return error_response(
            "Database operation failed",
            status_code=500,
            code="database_error"
        )

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        code = error.name.lower().replace(" ", "_")
        return error_response(
            error.description,
            status_code=error.code or 500,
            code=code
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception("Unhandled exception")
        return error_response(
            "Internal server error",
            status_code=500,
            code="internal_error"
        )
