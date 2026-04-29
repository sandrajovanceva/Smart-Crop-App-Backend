from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required
from flasgger import swag_from

from app.errors import BadRequestError, NotFoundError
from app.services.ai_service import AIService
from app.services.weather_service import WeatherService
from app.services.cache_service import CacheService

advisor_bp = Blueprint('advisor', __name__)


@advisor_bp.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200


@advisor_bp.route("/smart-advice", methods=["POST"])
@jwt_required()
@swag_from({
    "tags": ["Advisor"],
    "summary": "AI совет врз основа на време + култура",
    "security": [{"BearerAuth": []}],
    "parameters": [{
        "in": "body",
        "name": "body",
        "required": True,
        "schema": {
            "type": "object",
            "required": ["crop", "location"],
            "properties": {
                "crop": {"type": "string", "example": "домати"},
                "location": {"type": "string", "example": "Битола"},
                "country": {"type": "string", "example": "MK", "default": "MK"},
                "question": {"type": "string", "example": "Дали да наводнувам денес?"},
                "force_refresh": {
                    "type": "boolean",
                    "example": False,
                    "description": "Ако е true, се игнорира кешот и се генерира нов совет"
                },
            },
        },
    }],
    "responses": {
        "200": {"description": "Успешен совет"},
        "400": {"description": "Недостасуваат параметри"},
        "401": {"description": "Неавторизиран"},
        "404": {"description": "Локацијата не е пронајдена"},
        "500": {"description": "Грешка"},
    },
})
def smart_advice():
    data = request.get_json(silent=True)
    if data is None:
        raise BadRequestError("Invalid JSON body")

    crop = data.get("crop")
    location = data.get("location")
    country = data.get("country", "MK")
    question = data.get("question")
    force_refresh = data.get("force_refresh", False)
    current_app.logger.info(
        "smart advice request received",
        extra={
            "event": "advisor.smart_advice_started",
            "crop": crop,
            "location": location,
            "country": country,
            "force_refresh": force_refresh,
            "has_question": bool(question)
        }
    )

    if not crop:
        raise BadRequestError("Полето 'crop' е задолжително")

    if not location:
        raise BadRequestError("Полето 'location' е задолжително")

    if not force_refresh:
        cached_response = CacheService.get_cached_advice(
            crop=crop,
            location=location,
            country=country,
            question=question,
        )

        if cached_response:
            cached_response = {**cached_response, "from_cache": True}
            return jsonify(cached_response), 200

    weather_service = WeatherService()
    weather_data = weather_service.get_weather_by_location(
        location_name=location,
        country_code=country
    )

    if not weather_data:
        raise NotFoundError(f"Местото '{location}' не е пронајдено")

    ai_service = AIService()
    advice = ai_service.get_crop_advice(
        crop_name=crop,
        weather_data=weather_data,
        user_question=question,
    )

    response_data = {
        "weather": weather_data,
        "advice": advice,
        "from_cache": False,
    }

    CacheService.save_advice(
        crop=crop,
        location=location,
        country=country,
        question=question,
        response_data=response_data,
    )

    return jsonify(response_data), 200
