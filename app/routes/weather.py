import time
from datetime import datetime

from flasgger import swag_from
from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import db
from app.errors import BadRequestError, NotFoundError
from app.models.Field import Field
from app.models.Weather_data import WeatherData
from app.services.ai_service import AIService
from app.services.cache_service import CacheService
from app.services.weather_service import WeatherService
from app.utils.ai_advice_runner import get_cached_or_generate_advice

weather_bp = Blueprint("weather", __name__)

_ai_blocked_until = {"gemini": 0.0, "groq": 0.0}
_AI_BLOCK_SECONDS = 60


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
        country = field.country or None
        data = service.get_weather_by_location(field.location, country_code=country)
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
    user_id = get_jwt_identity()
    current_app.logger.info(
        "weather by location request received",
        extra={
            "event": "weather.by_location_started",
            "location": location,
        }
    )

    if not location or not location.strip():
        raise BadRequestError("Параметарот 'location' е задолжителен")

    service = WeatherService()
    field = Field.query.filter_by(user_id=user_id, location=location.strip()).first()
    if field and field.latitude is not None and field.longitude is not None:
        data = service.get_weather_by_coords(
            field.latitude, field.longitude, location_name=location.strip()
        )
    else:
        data = service.get_weather_by_location(location.strip(), country_code=None)
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
    country = request.args.get("country", type=str)
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
    user_id = get_jwt_identity()

    current_app.logger.info(
        "weather dashboard request received",
        extra={
            "event": "weather.dashboard_started",
            "location": location,
        }
    )

    if not location or not location.strip():
        raise BadRequestError("Параметарот 'location' е задолжителен")

    service = WeatherService()

    field = Field.query.filter_by(user_id=user_id, location=location.strip()).first()
    if field and field.latitude is not None and field.longitude is not None:
        weather_data = service.get_weather_by_coords(
            field.latitude, field.longitude, location_name=location.strip()
        )
    else:
        weather_data = service.get_weather_by_location(location.strip(), country_code=None)

    if not weather_data:
        raise NotFoundError(f"Местото '{location}' не е пронајдено")

    country = (weather_data.get("location") or {}).get("country")

    impacts_data = _get_weather_impacts(location.strip(), weather_data)
    impacts = extract_weather_impacts(impacts_data)

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


def _get_weather_impacts(location, weather_data):
    current = weather_data.get("current", {})
    forecast = weather_data.get("forecast_5_days", [])

    cached = CacheService.get_cached_advice(
        crop="weather-impacts",
        location=location,
        country=None,
        question="impacts"
    )
    if cached and isinstance(cached.get("weather_impacts"), list) and cached["weather_impacts"]:
        return cached

    forecast_lines = "\n".join(
        f"- {d['date']}: {d['temp_min']}°C to {d['temp_max']}°C, "
        f"rain {d['total_rain_mm']}mm, wind {d['wind_max']}m/s, {d['description']}"
        for d in forecast
    )

    prompt = f"""You are an agricultural weather impact assistant.

Analyze the weather data below and return a JSON object with exactly this structure:

{{
  "weather_impacts": [
    {{
      "label": "Temperature",
      "description": "specific crop impact based on real temperature values",
      "level": "Excellent",
      "percent": 75,
      "iconName": "Thermometer"
    }},
    {{
      "label": "Humidity",
      "description": "specific crop impact based on real humidity values",
      "level": "Good",
      "percent": 60,
      "iconName": "Droplets"
    }},
    {{
      "label": "Wind",
      "description": "specific crop impact based on real wind values",
      "level": "Poor",
      "percent": 30,
      "iconName": "Wind"
    }}
  ]
}}

Rules:
- weather_impacts must contain exactly 3 items: Temperature, Humidity, Wind.
- level must be one of: Excellent, Good, Moderate, Poor.
- percent must be a number from 0 to 100 based on actual conditions.
- descriptions must reference real numbers from the data below.
- Return ONLY the JSON object. No markdown. No extra text.

LOCATION: {location}
CURRENT: temp={current.get('temperature')}°C, humidity={current.get('humidity')}%, wind={current.get('wind_speed')}m/s, {current.get('description')}
5-DAY FORECAST:
{forecast_lines}
"""

    now = time.monotonic()
    ai = AIService()
    messages = [{"role": "user", "content": prompt}]

    if now >= _ai_blocked_until["gemini"]:
        try:
            result = ai.gemini_client.chat.completions.create(
                model=ai.gemini_model,
                messages=messages,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            raw = result.choices[0].message.content or ""
            parsed = AIService._extract_json(raw)
            if parsed and isinstance(parsed.get("weather_impacts"), list) and parsed["weather_impacts"]:
                CacheService.save_advice(crop="weather-impacts", location=location, country=None, response_data=parsed, question="impacts")
                return parsed
            current_app.logger.warning(f"Gemini returned invalid weather impacts structure: {raw[:200]}")
        except Exception as e:
            if "429" in str(e):
                _ai_blocked_until["gemini"] = now + _AI_BLOCK_SECONDS
            current_app.logger.warning(f"Gemini weather impacts failed: {e}. Trying Groq...")
    else:
        current_app.logger.info("Gemini skipped (circuit breaker active)")

    if ai.groq_client and now >= _ai_blocked_until["groq"]:
        try:
            result = ai.groq_client.chat.completions.create(
                model=ai.groq_model,
                messages=messages,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            raw = result.choices[0].message.content or ""
            parsed = AIService._extract_json(raw)
            if parsed and isinstance(parsed.get("weather_impacts"), list) and parsed["weather_impacts"]:
                CacheService.save_advice(crop="weather-impacts", location=location, country=None, response_data=parsed, question="impacts")
                return parsed
            current_app.logger.warning(f"Groq returned invalid weather impacts structure: {raw[:200]}")
        except Exception as e:
            if "429" in str(e):
                _ai_blocked_until["groq"] = now + _AI_BLOCK_SECONDS
            current_app.logger.warning(f"Groq weather impacts also failed: {e}. Using rule-based fallback.")
    elif ai.groq_client:
        current_app.logger.info("Groq skipped (circuit breaker active)")

    return _rule_based_impacts(current)


def _rule_based_impacts(current):
    temp = current.get("temperature")
    humidity = current.get("humidity")
    wind = current.get("wind_speed")

    if temp is None:
        temp_level, temp_pct, temp_desc = "Unknown", 50, "Temperature data unavailable."
    elif 15 <= temp <= 28:
        temp_level, temp_pct = "Excellent", 85
        temp_desc = f"Temperature of {temp}°C is ideal for most crops."
    elif 10 <= temp <= 32:
        temp_level, temp_pct = "Good", 65
        temp_desc = f"Temperature of {temp}°C is generally suitable for crops."
    elif 5 <= temp <= 36:
        temp_level, temp_pct = "Moderate", 45
        temp_desc = f"Temperature of {temp}°C may cause mild crop stress."
    else:
        temp_level, temp_pct = "Poor", 20
        temp_desc = f"Temperature of {temp}°C poses significant risk to crops."

    if humidity is None:
        hum_level, hum_pct, hum_desc = "Unknown", 50, "Humidity data unavailable."
    elif 40 <= humidity <= 70:
        hum_level, hum_pct = "Excellent", 80
        hum_desc = f"Humidity of {humidity}% is optimal for crop growth."
    elif 30 <= humidity <= 80:
        hum_level, hum_pct = "Good", 60
        hum_desc = f"Humidity of {humidity}% is acceptable for most crops."
    elif 20 <= humidity <= 85:
        hum_level, hum_pct = "Moderate", 40
        hum_desc = f"Humidity of {humidity}% may promote disease risk or drought stress."
    else:
        hum_level, hum_pct = "Poor", 20
        hum_desc = f"Humidity of {humidity}% poses risk of fungal disease or extreme dryness."

    if wind is None:
        wind_level, wind_pct, wind_desc = "Unknown", 50, "Wind data unavailable."
    elif wind <= 3:
        wind_level, wind_pct = "Excellent", 90
        wind_desc = f"Wind speed of {wind} m/s is calm — ideal for crops."
    elif wind <= 7:
        wind_level, wind_pct = "Good", 65
        wind_desc = f"Wind speed of {wind} m/s is moderate, minimal crop impact."
    elif wind <= 12:
        wind_level, wind_pct = "Moderate", 40
        wind_desc = f"Wind speed of {wind} m/s may cause some crop stress."
    else:
        wind_level, wind_pct = "Poor", 15
        wind_desc = f"Wind speed of {wind} m/s is high — risk of crop damage."

    return {
        "weather_impacts": [
            {"label": "Temperature", "description": temp_desc, "level": temp_level, "percent": temp_pct, "iconName": "Thermometer"},
            {"label": "Humidity", "description": hum_desc, "level": hum_level, "percent": hum_pct, "iconName": "Droplets"},
            {"label": "Wind", "description": wind_desc, "level": wind_level, "percent": wind_pct, "iconName": "Wind"},
        ]
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


def extract_weather_impacts(data):
    if not isinstance(data, dict):
        return []

    impacts = data.get("weather_impacts")

    if not isinstance(impacts, list):
        advice_data = data.get("advice", {}) or {}
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
