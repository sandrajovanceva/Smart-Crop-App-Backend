from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.utils.ai_advice_runner import get_cached_or_generate_advice
from app.utils.field_resolver import resolve_crop_location

diseases_bp = Blueprint("diseases", __name__)


@diseases_bp.route("/assess", methods=["POST"])
@jwt_required()
def assess_disease_risk():
    """
    Процена на ризик од болести и штетници
    ---
    tags:
      - Diseases
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
              description: ID на нивата. Ако е дадено, backend сам ги зема crop и location.
          example:
            field_id: 1
    responses:
      200:
        description: Gemini disease risk assessment
    """
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    crop, location, country, lat, lon = resolve_crop_location(data, user_id)

    disease_prompt = build_disease_prompt(
        crop=crop,
        location=location
    )

    advice_response = get_cached_or_generate_advice(
        crop=crop,
        location=location,
        country=country,
        prompt=disease_prompt,
        not_found_message=f"Местото '{location}' не е пронајдено",
        lat=lat,
        lon=lon,
    )

    return jsonify(
        extract_disease_info(
            advice_response=advice_response,
            crop=crop,
            location=location
        )
    ), 200


def build_disease_prompt(crop, location):
    today = datetime.utcnow().date().isoformat()

    return f"""
You are an agricultural plant disease and pest risk assessment assistant.

Create a disease and pest risk assessment for:
- crop: {crop}
- location: {location}
- current date: {today}

Use the provided weather data when assessing disease and pest risk.

Return ONLY valid JSON.
Do not include markdown.
Do not include explanation outside the JSON.
Do not wrap the JSON in ```json.

The JSON must have exactly this structure:

{{
  "summary": "short disease and pest risk summary",
  "risk_metrics": [
    {{
      "label": "Fungal Risk",
      "value": 0
    }},
    {{
      "label": "Bacterial Risk",
      "value": 0
    }},
    {{
      "label": "Viral Risk",
      "value": 0
    }},
    {{
      "label": "Soil Risk",
      "value": 0
    }}
  ],
  "trend_data": [
    {{
      "month": "Jan",
      "risk": 0
    }},
    {{
      "month": "Feb",
      "risk": 0
    }},
    {{
      "month": "Mar",
      "risk": 0
    }},
    {{
      "month": "Apr",
      "risk": 0
    }},
    {{
      "month": "May",
      "risk": 0
    }},
    {{
      "month": "Jun",
      "risk": 0
    }}
  ],
  "vulnerability_data": [
    {{
      "factor": "Temperature",
      "value": 0
    }},
    {{
      "factor": "Humidity",
      "value": 0
    }},
    {{
      "factor": "Rainfall",
      "value": 0
    }},
    {{
      "factor": "Wind",
      "value": 0
    }},
    {{
      "factor": "Soil Moisture",
      "value": 0
    }}
  ],
  "disease_alerts": [
    {{
      "name": "disease or pest name",
      "probability": 0,
      "severity": "Low",
      "symptoms": "likely symptoms",
      "prevention": "recommended prevention"
    }}
  ],
  "recommendations": [
    {{
      "title": "recommendation title",
      "description": "recommendation description",
      "badge": "Recommended"
    }}
  ]
}}

Rules:
- All numeric values must be from 0 to 100.
- severity must be one of: Low, Medium, High.
- disease_alerts must contain realistic disease or pest risks for the crop and weather.
- recommendations must be practical and related to disease/pest prevention.
- Do not copy the example numeric values.
- Generate values based on crop, location, current date, and provided weather data.
"""


def extract_disease_info(advice_response, crop, location):
    advice_data = advice_response.get("advice", {}) or {}
    advice_inner = advice_data.get("advice") or {}

    risk_metrics = _ensure_list(advice_inner.get("risk_metrics"))
    trend_data = _ensure_list(advice_inner.get("trend_data"))
    vulnerability_data = _ensure_list(advice_inner.get("vulnerability_data"))
    disease_alerts_from_ai = _ensure_list(advice_inner.get("disease_alerts"))
    recommendations = _ensure_list(advice_inner.get("recommendations"))

    alerts = [
        {
            "name": item.get("name"),
            "probability": item.get("probability"),
            "severity": item.get("severity"),
            "symptoms": item.get("symptoms"),
            "prevention": item.get("prevention"),
            "barColor": _bar_color_from_severity(item.get("severity")),
        }
        for item in disease_alerts_from_ai
        if isinstance(item, dict)
    ]

    return {
        "success": True,
        "crop": crop,
        "location": location,
        "summary": advice_inner.get("summary"),

        "risk_metrics": risk_metrics,
        "riskMetrics": risk_metrics,

        "trend_data": trend_data,
        "trendData": trend_data,

        "vulnerability_factors": vulnerability_data,
        "vulnerabilityData": vulnerability_data,

        "alerts": alerts,
        "diseaseAlerts": alerts,

        "prevention_recommendations": recommendations,
        "recommendations": recommendations,

        "from_cache": advice_response.get("from_cache", False),
    }


def _ensure_list(value):
    if isinstance(value, list):
        return value

    return []


def _bar_color_from_severity(severity):
    if severity == "High":
        return "bg-red-500"

    if severity == "Medium":
        return "bg-orange-500"

    if severity == "Low":
        return "bg-green-500"

    return "bg-gray-500"
