import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone

from flask import g, has_request_context, request
from flask_jwt_extended import get_jwt_identity


_RESERVED_LOG_RECORD_ATTRS = set(logging.LogRecord(
    name="",
    level=0,
    pathname="",
    lineno=0,
    msg="",
    args=(),
    exc_info=None
).__dict__)


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = None
        record.user_id = None

        if has_request_context():
            record.request_id = getattr(g, "request_id", None)
            record.user_id = getattr(g, "current_user_id", None) or _get_current_user_id()

        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module_name": record.module,
            "method_name": record.funcName,
            "line_number": record.lineno,
        }

        if getattr(record, "request_id", None):
            payload["request_id"] = record.request_id

        if getattr(record, "user_id", None):
            payload["user_id"] = record.user_id

        if getattr(record, "class_name", None):
            payload["class_name"] = record.class_name

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_ATTRS or key in payload or key.startswith("_"):
                continue
            payload[key] = _json_safe(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(app):
    log_level_name = app.config.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(RequestContextFilter())

    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(log_level)
    app.logger.propagate = False

    logging.getLogger("werkzeug").setLevel(log_level)


def register_request_logging(app):
    @app.before_request
    def start_request_logging():
        g.request_id = _get_request_id()
        g.request_started_at = time.perf_counter()

    @app.after_request
    def log_request(response):
        duration_ms = _get_request_duration_ms()
        user_id = _get_current_user_id()
        g.current_user_id = user_id

        response.headers["X-Request-ID"] = g.request_id

        app.logger.info(
            "request completed",
            extra={
                "event": "http.request_completed",
                "method": request.method,
                "path": request.path,
                "route": str(request.url_rule) if request.url_rule else None,
                "endpoint": request.endpoint,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": _get_client_ip(),
                "user_agent": _truncate(request.user_agent.string, 200),
                "content_length": request.content_length,
            }
        )

        return response


def _get_request_id():
    request_id = request.headers.get("X-Request-ID", "").strip()
    if not request_id:
        return str(uuid.uuid4())
    return _truncate(request_id, 128)


def _get_request_duration_ms():
    started_at = getattr(g, "request_started_at", None)
    if started_at is None:
        return None
    return round((time.perf_counter() - started_at) * 1000, 2)


def _get_current_user_id():
    try:
        return get_jwt_identity()
    except Exception:
        return None


def _get_client_ip():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.remote_addr


def _truncate(value, max_length):
    if not value:
        return value
    return value[:max_length]


def _json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)
