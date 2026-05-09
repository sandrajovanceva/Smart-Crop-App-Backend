from datetime import datetime

from flasgger import swag_from
from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import db
from app.errors import BadRequestError, NotFoundError
from app.models.Field import Field
from app.models.Weather_data import WeatherData
from app.services.weather_service import WeatherService
from app.utils.ai_advice_runner import get_cached_or_generate_advice

weather_bp = Blueprint("weather", __name__)


def _parse_coord(value, lo, hi, name):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise BadRequestError(f"{name} must be a number")
    if v < lo or v > hi:
        raise BadRequestError(f"{name} must be between {lo} and {hi}")
    return v


@weather_bp.route("/by-coords", methods=["GET"])
@jwt_required()
@swag_from({
    "tags": ["Weather"],
    "summary": "Време по координати (директен повик до OpenWeather, без geocoding)",
    "description": "Користи го кога frontend веќе има lat/lon (пр. од Leaflet мапа или од сочуваното поле).",
    "security": [{"BearerAuth": []}],
    "parameters": [
        {"name": "lat", "in": "query", "type": "number", "required": True, "example": 41.9981},
        {"name": "lon", "in": "query", "type": "number", "required": True, "example": 21.4254},
        {"name": "name", "in": "query", "type": "string", "required": False,
         "description": "Опционо име на местото за приказ"},
    ],
    "responses": {
        "200": {
            "description": "Успешен одговор со време + 5-дневна прогноза + alerts",
            "schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "object",
                        "properties": {
                            "found_name": {"type": "string", "example": "Скопје"},
                            "country": {"type": "string", "example": "MK"},
                            "lat": {"type": "number", "example": 41.9981},
                            "lon": {"type": "number", "example": 21.4254},
                        }
                    },
                    "current": {
                        "type": "object",
                        "properties": {
                            "temperature": {"type": "number", "example": 18.5},
                            "feels_like": {"type": "number", "example": 17.2},
                            "humidity": {"type": "integer", "example": 65},
                            "pressure": {"type": "integer", "example": 1015},
                            "wind_speed": {"type": "number", "example": 3.2},
                            "wind_speed_kmh": {"type": "number", "example": 11.5},
                            "visibility": {"type": "number", "example": 10.0},
                            "description": {"type": "string", "example": "малку облачно"},
                            "icon": {"type": "string", "example": "02d"},
                            "rain_1h_mm": {"type": "number", "example": 0},
                        }
                    },
                    "forecast_5_days": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": "string", "example": "2026-05-04"},
                                "temp_min": {"type": "number", "example": 12.3},
                                "temp_max": {"type": "number", "example": 22.1},
                                "temp_avg": {"type": "number", "example": 17.5},
                                "humidity_avg": {"type": "integer", "example": 68},
                                "total_rain_mm": {"type": "number", "example": 2.4},
                                "rain_probability": {"type": "integer", "example": 60},
                                "description": {"type": "string", "example": "лесен дожд"},
                            }
                        }
                    },
                    "agricultural_alerts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "severity": {"type": "string", "example": "medium"},
                                "type": {"type": "string", "example": "fungal_risk"},
                                "message": {"type": "string", "example": "Висока влажност - ризик од габични болести"},
                            }
                        }
                    }
                }
            }
        },
        "400": {"description": "Невалидни координати"},
        "401": {"description": "Неавторизиран"},
    }
})
def weather_by_coords():
    lat = _parse_coord(request.args.get("lat"), -90, 90, "lat")
    lon = _parse_coord(request.args.get("lon"), -180, 180, "lon")
    name = request.args.get("name", type=str)

    service = WeatherService()
    data = service.get_weather_by_coords(lat, lon, location_name=name)
    return jsonify(data), 200


@weather_bp.route("/by-field/<int:field_id>", methods=["GET"])
@jwt_required()
@swag_from({
    "tags": ["Weather"],
    "summary": "Време за конкретна нива (по сочуваните lat/lon на нивата)",
    "description": "Ако нивата има lat/lon → директен повик. Ако не → fallback по location.",
    "security": [{"BearerAuth": []}],
    "parameters": [
        {
            "name": "field_id",
            "in": "path",
            "type": "integer",
            "required": True,
            "description": "ID на нивата"
        }
    ],
    "responses": {
        "200": {"description": "Успешен одговор"},
        "401": {"description": "Неавторизиран"},
        "404": {"description": "Нивата не е пронајдена"},
    },
})
def weather_by_field(field_id):
    user_id = get_jwt_identity()
    field = Field.query.filter_by(id=field_id, user_id=user_id).first()
    if not field:
        raise NotFoundError("Field not found")

    service = WeatherService()
    if field.latitude is not None and field.longitude is not None:
        data = service.get_weather_by_coords(field.latitude, field.longitude, location_name=field.location)
    else:
        data = service.get_weather_by_location(field.location, country_code=field.country or "MK")
        if not data:
            raise NotFoundError(f"Не може да се добие време за '{field.location}'")

    _save_weather_snapshot(field_id, data)

    return jsonify(data), 200


def _save_weather_snapshot(field_id, weather_data):
    current = weather_data.get("current") or {}
    try:
        entry = WeatherData(
            field_id=field_id,
            temperature=current.get("temperature"),
            humidity=current.get("humidity"),
            rainfall=current.get("rain_1h_mm", 0),
            wind_speed=current.get("wind_speed"),
            description=current.get("description"),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()


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
    current_app.logger.info(
        "weather by location request received",
        extra={
            "event": "weather.by_location_started",
            "location": location,
            "country": country
        }
    )

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
    current_app.logger.info(
        "weather location search request received",
        extra={
            "event": "weather.search_started",
            "query": query,
            "country": country
        }
    )

    if not query or not query.strip():
        raise BadRequestError("Параметарот 'q' е задолжителен")

    service = WeatherService()
    results = service.search_locations(query.strip(), country_code=country)
    return jsonify({"results": results}), 200


@weather_bp.route("/dashboard", methods=["GET"])
@jwt_required()
@swag_from({
    "tags": ["Weather"],
    "summary": "Weather dashboard data",
    "description": "Враќа податоци прилагодени за WeatherPage dashboard приказ.",
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
def weather_dashboard():
    location = request.args.get("location", type=str)
    country = request.args.get("country", default="MK", type=str)

    current_app.logger.info(
        "weather dashboard request received",
        extra={
            "event": "weather.dashboard_started",
            "location": location,
            "country": country
        }
    )

    if not location or not location.strip():
        raise BadRequestError("Параметарот 'location' е задолжителен")

    service = WeatherService()

    weather_data = service.get_weather_by_location(
        location.strip(),
        country_code=country
    )

    if not weather_data:
        raise NotFoundError(f"Местото '{location}' не е пронајдено")

    weather_prompt = build_weather_impacts_prompt(location.strip())

    advice_response = get_cached_or_generate_advice(
        crop="weather-dashboard",
        location=location.strip(),
        country=country,
        prompt=weather_prompt,
        weather_data=weather_data,
        not_found_message=f"Местото '{location}' не е пронајдено"
    )

    impacts = extract_weather_impacts(advice_response)

    dashboard_data = build_weather_dashboard_response(
        weather_data,
        location.strip(),
        impacts
    )

    return jsonify(dashboard_data), 200


def build_weather_dashboard_response(weather_data, location, impacts):
    current = weather_data.get("current", {})
    forecast = weather_data.get("forecast") or weather_data.get("forecast_5_days", [])
    forecast_24h = weather_data.get("forecast_24h", [])

    temperature = current.get("temperature")
    humidity = current.get("humidity")
    wind_speed = current.get("wind_speed")
    wind_speed_kmh = current.get("wind_speed_kmh")
    visibility = current.get("visibility")
    pressure = current.get("pressure")
    description = current.get("description", "Unknown")

    return {
        "success": True,
        "location": location,
        "current": {
            "temperature": temperature,
            "description": description,
            "lastUpdated": "Just now"
        },
        "currentMetrics": [
            {
                "label": "Humidity",
                "value": f"{humidity}%" if humidity is not None else "N/A",
                "iconName": "Droplets"
            },
            {
                "label": "Wind Speed",
                "value": f"{wind_speed_kmh} km/h" if wind_speed_kmh is not None else "N/A",
                "iconName": "Wind"
            },
            {
                "label": "Visibility",
                "value": f"{visibility} km" if visibility is not None else "N/A",
                "iconName": "Eye"
            },
            {
                "label": "Pressure",
                "value": f"{pressure} mb" if pressure is not None else "N/A",
                "iconName": "Gauge"
            }
        ],
        "forecast": _build_forecast_data(forecast),
        "temperatureData": _build_temperature_data(forecast_24h),
        "humidityData": _build_humidity_data(forecast),
        "rainfallData": _build_rainfall_data(forecast),
        "impacts": impacts
    }


def build_weather_impacts_prompt(location):
    today = datetime.utcnow().date().isoformat()

    return f"""
You are an agricultural weather impact assistant.

Create weather impact analysis for:
- location: {location}
- current date: {today}

Use the provided real-time weather data and forecast.

Return ONLY valid JSON.
Do not include markdown.
Do not include explanation outside the JSON.
Do not wrap the JSON in ```json.

The JSON must have exactly this structure:

{{
  "weather_impacts": [
    {{
      "label": "Temperature",
      "description": "specific crop-related weather impact",
      "level": "Excellent",
      "percent": 0,
      "iconName": "Thermometer",
      "iconBg": "bg-green-100",
      "iconColor": "text-green-600",
      "barColor": "bg-green-500",
      "levelColor": "text-green-600"
    }},
    {{
      "label": "Humidity",
      "description": "specific crop-related weather impact",
      "level": "Good",
      "percent": 0,
      "iconName": "Droplets",
      "iconBg": "bg-yellow-100",
      "iconColor": "text-yellow-600",
      "barColor": "bg-yellow-500",
      "levelColor": "text-yellow-600"
    }},
    {{
      "label": "Wind",
      "description": "specific crop-related weather impact",
      "level": "Poor",
      "percent": 0,
      "iconName": "Wind",
      "iconBg": "bg-red-100",
      "iconColor": "text-red-600",
      "barColor": "bg-red-500",
      "levelColor": "text-red-600"
    }}
  ]
}}

Rules:
- weather_impacts must contain 3 items: Temperature, Humidity, Wind.
- percent must be a number from 0 to 100.
- level must be one of: Excellent, Good, Poor, Unknown.
- Generate descriptions and percent values based on the provided weather data.
- Do not copy the example percent values.
"""


_IMPACT_LEVEL_STYLES = {
    "Excellent": {
        "iconBg": "bg-green-100",
        "iconColor": "text-green-600",
        "barColor": "bg-green-500",
        "levelColor": "text-green-600",
    },
    "Good": {
        "iconBg": "bg-green-100",
        "iconColor": "text-green-600",
        "barColor": "bg-green-500",
        "levelColor": "text-green-600",
    },
    "Moderate": {
        "iconBg": "bg-yellow-100",
        "iconColor": "text-yellow-600",
        "barColor": "bg-yellow-500",
        "levelColor": "text-yellow-600",
    },
    "Poor": {
        "iconBg": "bg-red-100",
        "iconColor": "text-red-600",
        "barColor": "bg-red-500",
        "levelColor": "text-red-600",
    },
    "Unknown": {
        "iconBg": "bg-gray-100",
        "iconColor": "text-gray-500",
        "barColor": "bg-gray-400",
        "levelColor": "text-gray-500",
    },
}

_VALID_IMPACT_LEVELS = {"Excellent", "Good", "Moderate", "Poor", "Unknown"}


def extract_weather_impacts(advice_response):
    advice_data = advice_response.get("advice", {}) or {}
    advice_inner = advice_data.get("advice") or {}

    impacts = advice_inner.get("weather_impacts")

    if not isinstance(impacts, list):
        return []

    result = []
    for impact in impacts:
        if not isinstance(impact, dict):
            continue
        level = impact.get("level") if impact.get("level") in _VALID_IMPACT_LEVELS else "Unknown"
        styles = _IMPACT_LEVEL_STYLES[level]
        result.append({
            **impact,
            "level": level,
            "iconBg": styles["iconBg"],
            "iconColor": styles["iconColor"],
            "barColor": styles["barColor"],
            "levelColor": styles["levelColor"],
        })

    return result


def _build_forecast_data(forecast):
    result = []

    for item in forecast[:5]:
        date_value = item.get("date")

        result.append({
            "day": _day_label(date_value),
            "date": _date_label(date_value),
            "temp": item.get("temp_avg"),
            "tempMin": item.get("temp_min"),
            "tempMax": item.get("temp_max"),
            "humidity": item.get("humidity_avg"),
            "rainfall": item.get("total_rain_mm", 0),
            "rainProbability": item.get("rain_probability"),
            "windMax": item.get("wind_max"),
            "description": item.get("description"),
        })

    return result


def _build_temperature_data(forecast_24h):
    return [
        {"time": item.get("time"), "temp": item.get("temp")}
        for item in forecast_24h
    ]


def _build_humidity_data(forecast):
    result = []

    for item in forecast[:5]:
        result.append({
            "day": _day_label(item.get("date")),
            "humidity": item.get("humidity_avg")
        })

    return result


def _build_rainfall_data(forecast):
    result = []

    for item in forecast[:5]:
        result.append({
            "month": _date_label(item.get("date")),
            "rainfall": item.get("total_rain_mm", 0)
        })

    return result


def _day_label(date_value):
    if not date_value:
        return None

    try:
        return datetime.fromisoformat(date_value).strftime("%a")
    except ValueError:
        return date_value


def _date_label(date_value):
    if not date_value:
        return None

    try:
        d = datetime.fromisoformat(date_value)
        return f"{d.strftime('%B')} {d.day}"
    except ValueError:
        return date_value
