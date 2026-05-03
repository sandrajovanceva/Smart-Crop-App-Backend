from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.utils.ai_advice_runner import get_cached_or_generate_advice
from app.utils.field_resolver import resolve_crop_location

fertilizer_bp = Blueprint("fertilizer", __name__)


@fertilizer_bp.route("/recommend", methods=["POST"])
@jwt_required()
def recommend_fertilizer():
    """
    AI препорака за ѓубрење
    ---
    tags:
      - Fertilizer
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
    schema:
      type: object
      properties:
        field_id:
          type: integer
          example: 1
          description: ID на нивата. Backend сам ги зема crop и location.
        growth_stage:
          type: string
          example: 'Vegetative'
        country:
          type: string
          default: 'MK'
          example: 'MK'
      example:
        field_id: 1
        growth_stage: 'Vegetative'
        country: 'MK'
        description: Gemini fertilizer recommendations
    """
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    growth_stage = (
            data.get("growth_stage")
            or data.get("growthStage")
            or "Vegetative"
    )

    crop, location, country = resolve_crop_location(data, user_id)

    fertilizer_prompt = build_fertilizer_prompt(
        crop=crop,
        location=location,
        growth_stage=growth_stage
    )

    advice_response = get_cached_or_generate_advice(
        crop=crop,
        location=location,
        country=country,
        prompt=fertilizer_prompt,
        not_found_message=f"Местото '{location}' не е пронајдено"
    )

    return jsonify(
        extract_fertilizer_info(
            advice_response=advice_response,
            crop=crop,
            location=location,
            growth_stage=growth_stage
        )
    ), 200


def build_fertilizer_prompt(crop, location, growth_stage):
    today = datetime.utcnow().date().isoformat()

    return f"""
You are an agricultural fertilizer recommendation assistant.

Create a structured fertilizer recommendation for:
- crop: {crop}
- location: {location}
- growth stage: {growth_stage}
- current date: {today}

Use the provided weather data when deciding the fertilizer recommendation.

Return ONLY valid JSON.
Do not include markdown.
Do not include explanation outside the JSON.
Do not wrap the JSON in ```json.

The JSON response MUST include these exact top-level fields:
- summary
- fertilizer_schedule
- ai_metrics
- yield_data
- guidelines
- recommended_activities

The JSON must have exactly this structure:

{{
  "summary": "short fertilizer recommendation summary",
  "fertilizer_schedule": [
    {{
      "week": "Week 1",
      "dates": "date range based on current date",
      "type": "fertilizer type with NPK ratio if relevant",
      "rate": "rate in kg/acre",
      "status": "Pending"
    }},
    {{
      "week": "Week 4",
      "dates": "date range based on current date",
      "type": "fertilizer type with NPK ratio if relevant",
      "rate": "rate in kg/acre",
      "status": "Scheduled"
    }},
    {{
      "week": "Week 8",
      "dates": "date range based on current date",
      "type": "fertilizer type with NPK ratio if relevant",
      "rate": "rate in kg/acre",
      "status": "Scheduled"
    }}
  ],
  "ai_metrics": [
    {{
      "label": "Recommended Type",
      "value": "specific fertilizer recommendation"
    }},
    {{
      "label": "Application Rate",
      "value": "specific rate in kg/acre"
    }},
    {{
      "label": "Expected Yield Increase",
      "value": "estimated percentage"
    }}
  ],
  "yield_data": [
    {{
      "stage": "Current",
      "yield": 0
    }},
    {{
      "stage": "After Week 4",
      "yield": 0
    }},
    {{
      "stage": "Expected",
      "yield": 0
    }}
  ],
  "guidelines": [
    {{
      "title": "Best Time to Apply",
      "text": "specific practical guideline"
    }},
    {{
      "title": "Application Method",
      "text": "specific practical guideline"
    }},
    {{
      "title": "Precautions",
      "text": "specific practical guideline"
    }},
    {{
      "title": "Monitoring",
      "text": "specific practical guideline"
    }}
  ],
  "recommended_activities": [
    "short fertilizer-related activity recommendation"
  ]
}}

Strict rules:
- fertilizer_schedule MUST contain exactly 3 items.
- ai_metrics MUST contain at least 3 items.
- yield_data MUST contain exactly 3 items.
- guidelines MUST contain at least 4 items.
- Do NOT return only summary and recommended_activities.
- Do NOT omit fertilizer_schedule.
- Do NOT omit ai_metrics.
- Do NOT omit yield_data.
- Do NOT omit guidelines.
- status must be one of: Pending, Scheduled, Completed.
- Use kg/acre for fertilizer rates.
- yield must be a number from 0 to 100.
- Do not copy example values.
- Generate all schedule dates, fertilizer rates, metrics, yield estimates, and guidelines based on the crop, growth stage, location, current date, and provided weather data.
"""


def extract_fertilizer_info(advice_response, crop, location, growth_stage):
    """
    Преобликува Gemini response во структура што ја очекува frontend `FertilizerPage`.

    Сите fertilizer податоци доаѓаат од Gemini.
    Backend само додава statusColor според status.
    """
    advice_data = advice_response.get("advice", {}) or {}
    advice_inner = advice_data.get("advice") or {}

    schedule_from_ai = _ensure_list(advice_inner.get("fertilizer_schedule"))
    ai_metrics = _ensure_list(advice_inner.get("ai_metrics"))
    yield_data = _ensure_list(advice_inner.get("yield_data"))
    guidelines = _ensure_list(advice_inner.get("guidelines"))
    activities = _ensure_list(advice_inner.get("recommended_activities"))

    schedule = [
        {
            "week": item.get("week"),
            "dates": item.get("dates"),
            "type": item.get("type"),
            "rate": item.get("rate"),
            "status": item.get("status"),
            "statusColor": _status_color(item.get("status")),
        }
        for item in schedule_from_ai
        if isinstance(item, dict)
    ]

    ai_recommendations = [
        {
            "title": item,
            "description": item
        }
        for item in activities[:5]
        if isinstance(item, str)
    ]

    return {
        "success": True,
        "crop": crop,
        "location": location,

        "growth_stage": growth_stage,
        "growthStage": growth_stage,

        "summary": advice_inner.get("summary"),

        "schedule": schedule,

        "yield_data": yield_data,
        "yieldData": yield_data,

        "ai_metrics": ai_metrics,
        "aiMetrics": ai_metrics,

        "ai_recommendations": ai_recommendations,
        "aiRecommendations": ai_recommendations,

        "guidelines": guidelines,

        "from_cache": advice_response.get("from_cache", False),
    }


def _ensure_list(value):
    if isinstance(value, list):
        return value

    return []


def _status_color(status):
    if status == "Pending":
        return "bg-orange-100 text-orange-600"

    if status == "Scheduled":
        return "bg-blue-100 text-blue-600"

    if status == "Completed":
        return "bg-green-100 text-green-600"

    return "bg-gray-100 text-gray-600"
