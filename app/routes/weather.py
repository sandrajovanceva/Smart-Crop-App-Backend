from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from flasgger import swag_from
from app.errors import BadRequestError, NotFoundError
from app.services.weather_service import WeatherService

weather_bp = Blueprint("weather", __name__)


@weather_bp.route("/by-location", methods=["GET"])
@jwt_required()
@swag_from({
    "tags": ["Weather"],
    "summary": "Временски услови по име на место",
    "description": "Враќа тековно време, 5-дневна прогноза и земјоделски сигнали.",
    "security": [{"BearerAuth": []}],
    "parameters": [
        {
            "name": "location",
            "in": "query",
            "type": "string",
            "required": True,
            "description": "Име на град, село или регион"
        },
        {
            "name": "country",
            "in": "query",
            "type": "string",
            "required": False,
            "default": "MK"
        },
    ],
    "responses": {
        "200": {"description": "Успешен одговор"},
        "400": {"description": "Недостасува параметар"},
        "401": {"description": "Неавторизиран"},
        "404": {"description": "Местото не е пронајдено"},
    },
})
def weather_by_location():
    location = request.args.get("location", type=str)
    country = request.args.get("country", default="MK", type=str)

    if not location or not location.strip():
        raise BadRequestError("Параметарот 'location' е задолжителен")

    service = WeatherService()
    data = service.get_weather_by_location(location.strip(), country_code=country)
    if not data:
        raise NotFoundError(f"Местото '{location}' не е пронајдено")
    return jsonify(data), 200


@weather_bp.route("/search", methods=["GET"])
@jwt_required()
@swag_from({
    "tags": ["Weather"],
    "summary": "Пребарај можни локации",
    "description": "Пребарува можни локации за дадено име. Корисно за места со исто име но различни координати (пр. „Ново Село“).",
    "security": [{"BearerAuth": []}],
    "parameters": [
        {"name": "q", "in": "query", "type": "string", "required": True},
        {"name": "country", "in": "query", "type": "string", "required": False, "default": "MK"},
    ],
    "responses": {
        "200": {"description": "Успешен одговор"},
        "401": {"description": "Неавторизиран"},
    },
})
def search_locations():
    query = request.args.get("q", type=str)
    country = request.args.get("country", default="MK", type=str)

    if not query or not query.strip():
        raise BadRequestError("Параметарот 'q' е задолжителен")

    service = WeatherService()
    results = service.search_locations(query.strip(), country_code=country)
    return jsonify({"results": results}), 200
