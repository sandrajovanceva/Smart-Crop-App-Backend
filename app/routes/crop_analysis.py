from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.utils.ai_advice_runner import get_cached_or_generate_advice
from app.utils.field_resolver import resolve_crop_location

crop_analysis_bp = Blueprint("crop_analysis", __name__)


@crop_analysis_bp.route("/analyze", methods=["POST"])
@jwt_required()
def analyze_crop():
    """
    schema:
      type: object
      properties:
        field_id:
          type: integer
          example: 1
          description: ID на нивата. Backend сам ги зема crop и location.
        country:
          type: string
          default: 'MK'
          example: 'MK'
      example:
        field_id: 1
        country: 'MK'
    """
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    crop, location, country = resolve_crop_location(data, user_id)

    analysis_prompt = build_crop_analysis_prompt(
        crop=crop,
        location=location
    )

    advice_response = get_cached_or_generate_advice(
        crop=crop,
        location=location,
        country=country,
        prompt=analysis_prompt,
        not_found_message=f"Location '{location}' not found"
    )

    return jsonify(
        build_crop_analysis_response(
            crop=crop,
            location=location,
            advice_response=advice_response
        )
    ), 200


def build_crop_analysis_prompt(crop, location):
    today = datetime.utcnow().date().isoformat()

    return f"""
You are an agricultural crop health analysis assistant.

Create a crop health analysis for:
- crop: {crop}
- location: {location}
- current date: {today}

Use the provided weather data when analyzing crop health.

Return ONLY valid JSON.
Do not include markdown.
Do not include explanation outside the JSON.
Do not wrap the JSON in ```json.

The JSON must have exactly this structure:

{{
  "summary": "short crop health summary",
  "health_data": [
    {{
      "name": "Health",
      "value": 0,
      "fill": "#2e5d40"
    }}
  ],
  "recommendations": [
    {{
      "title": "recommendation title",
      "description": "specific recommendation",
      "priority": "Medium",
      "type": "irrigation"
    }}
  ],
  "conditions": [
    {{
      "label": "Temperature",
      "value": "value with unit",
      "color": "text-green-600"
    }},
    {{
      "label": "Humidity",
      "value": "value with unit",
      "color": "text-blue-600"
    }},
    {{
      "label": "Rainfall",
      "value": "value with unit",
      "color": "text-cyan-600"
    }}
  ],
  "disease_risks": [
    {{
      "name": "Fungal Risk",
      "risk": 0
    }},
    {{
      "name": "Bacterial Risk",
      "risk": 0
    }},
    {{
      "name": "Viral Risk",
      "risk": 0
    }}
  ]
}}

Rules:
- health_data value must be from 0 to 100.
- disease risk values must be from 0 to 100.
- priority must be one of: Low, Medium, High.
- recommendation type must be one of: irrigation, fertilizer, disease, weather, general.
- Use the provided weather data, crop, location, and current date.
- Do not copy the example values.
"""


def build_crop_analysis_response(crop, location, advice_response):
    advice_data = advice_response.get("advice", {}) or {}
    advice_inner = advice_data.get("advice") or {}

    health_data = _ensure_list(advice_inner.get("health_data"))
    recommendations = _ensure_list(advice_inner.get("recommendations"))
    conditions = _ensure_list(advice_inner.get("conditions"))
    disease_risks = _ensure_list(advice_inner.get("disease_risks"))

    return {
        "success": True,
        "crop": crop,
        "location": location,
        "summary": advice_inner.get("summary"),

        "healthData": health_data,
        "health_data": health_data,

        "recommendations": recommendations,

        "conditions": conditions,

        "diseaseRisks": disease_risks,
        "disease_risks": disease_risks,

        "from_cache": advice_response.get("from_cache", False),
    }


def _ensure_list(value):
    if isinstance(value, list):
        return value

    return []
