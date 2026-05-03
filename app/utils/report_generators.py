from datetime import datetime

from app.errors import BadRequestError, NotFoundError
from app.routes.crop_analysis import build_crop_analysis_prompt, build_crop_analysis_response
from app.routes.diseases import build_disease_prompt, extract_disease_info
from app.routes.fertilizer import build_fertilizer_prompt, extract_fertilizer_info
from app.routes.weather import (
    build_weather_dashboard_response,
    build_weather_impacts_prompt,
    extract_weather_impacts,
)
from app.services.weather_service import WeatherService
from app.utils.ai_advice_runner import get_cached_or_generate_advice


def generate_report_payload(field, report_type, data):
    country = data.get("country") or getattr(field, "country", None) or "MK"
    crop = field.crop_type
    location = field.location

    if report_type == "Crop Analysis":
        prompt = build_crop_analysis_prompt(crop=crop, location=location)

        advice_response = get_cached_or_generate_advice(
            crop=crop,
            location=location,
            country=country,
            prompt=prompt,
            not_found_message=f"Location '{location}' not found"
        )

        return build_crop_analysis_response(
            crop=crop,
            location=location,
            advice_response=advice_response
        )

    if report_type == "Disease Risk":
        prompt = build_disease_prompt(crop=crop, location=location)

        advice_response = get_cached_or_generate_advice(
            crop=crop,
            location=location,
            country=country,
            prompt=prompt,
            not_found_message=f"Местото '{location}' не е пронајдено"
        )

        return extract_disease_info(
            advice_response=advice_response,
            crop=crop,
            location=location
        )

    if report_type == "Fertilizer":
        growth_stage = (
            data.get("growth_stage")
            or data.get("growthStage")
            or "Vegetative"
        )

        prompt = build_fertilizer_prompt(
            crop=crop,
            location=location,
            growth_stage=growth_stage
        )

        advice_response = get_cached_or_generate_advice(
            crop=crop,
            location=location,
            country=country,
            prompt=prompt,
            not_found_message=f"Местото '{location}' не е пронајдено"
        )

        return extract_fertilizer_info(
            advice_response=advice_response,
            crop=crop,
            location=location,
            growth_stage=growth_stage
        )

    if report_type == "Weather Analysis":
        service = WeatherService()
        weather_data = service.get_weather_by_location(location, country_code=country)

        if not weather_data:
            raise NotFoundError(f"Местото '{location}' не е пронајдено")

        weather_prompt = build_weather_impacts_prompt(location)

        advice_response = get_cached_or_generate_advice(
            crop="weather-dashboard",
            location=location,
            country=country,
            prompt=weather_prompt,
            weather_data=weather_data,
            not_found_message=f"Местото '{location}' не е пронајдено"
        )

        impacts = extract_weather_impacts(advice_response)

        return build_weather_dashboard_response(
            weather_data=weather_data,
            location=location,
            impacts=impacts
        )

    if report_type == "Irrigation":
        prompt = _build_irrigation_report_prompt(
            crop=crop,
            location=location
        )

        advice_response = get_cached_or_generate_advice(
            crop=crop,
            location=location,
            country=country,
            prompt=prompt,
            not_found_message=f"Местото '{location}' не е пронајдено"
        )

        return _extract_irrigation_report_info(
            advice_response=advice_response,
            crop=crop,
            location=location
        )

    raise BadRequestError(f"Unsupported report_type: {report_type}")


def _build_irrigation_report_prompt(crop, location):
    today = datetime.utcnow().date().isoformat()

    return f"""
You are an agricultural irrigation recommendation assistant.

Create an irrigation report for:
- crop: {crop}
- location: {location}
- current date: {today}

Use the provided weather data and forecast.

Return ONLY valid JSON.
Do not include markdown.
Do not include explanation outside the JSON.
Do not wrap the JSON in ```json.

The JSON must have exactly this structure:

{{
  "summary": "short irrigation summary",
  "irrigation_recommendations": [
    {{
      "title": "recommendation title",
      "description": "specific irrigation recommendation",
      "priority": "Medium"
    }}
  ],
  "water_needs": [
    {{
      "label": "Current Need",
      "value": "value"
    }},
    {{
      "label": "Rainfall Impact",
      "value": "value"
    }},
    {{
      "label": "Next Irrigation",
      "value": "value"
    }}
  ],
  "schedule": [
    {{
      "period": "Today",
      "recommendation": "specific action"
    }},
    {{
      "period": "Next 3 days",
      "recommendation": "specific action"
    }},
    {{
      "period": "Next week",
      "recommendation": "specific action"
    }}
  ]
}}

Rules:
- recommendations must be based on crop, location, current date, and provided weather data.
- priority must be one of: Low, Medium, High.
- Do not copy the example values.
"""


def _extract_irrigation_report_info(advice_response, crop, location):
    advice_data = advice_response.get("advice", {}) or {}
    advice_inner = advice_data.get("advice") or {}

    return {
        "success": True,
        "crop": crop,
        "location": location,
        "summary": advice_inner.get("summary"),
        "irrigation_recommendations": _ensure_list(
            advice_inner.get("irrigation_recommendations")
        ),
        "water_needs": _ensure_list(advice_inner.get("water_needs")),
        "schedule": _ensure_list(advice_inner.get("schedule")),
        "from_cache": advice_response.get("from_cache", False),
    }


def _ensure_list(value):
    if isinstance(value, list):
        return value

    return []