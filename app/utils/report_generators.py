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
    country = data.get("country") or getattr(field, "country", None)
    crop = field.crop_type
    location = field.location

    lat = field.latitude
    lon = field.longitude

    if report_type == "Crop Analysis":
        prompt = build_crop_analysis_prompt(crop=crop, location=location)

        advice_response = get_cached_or_generate_advice(
            crop=crop,
            location=location,
            country=country,
            prompt=prompt,
            not_found_message=f"Location '{location}' not found",
            lat=lat,
            lon=lon,
        )

        payload = build_crop_analysis_response(
            crop=crop,
            location=location,
            advice_response=advice_response
        )
        payload["summary"] = _summarize_crop_analysis_payload(payload, crop, location)
        return payload

    if report_type == "Disease Risk":
        prompt = build_disease_prompt(crop=crop, location=location)

        advice_response = get_cached_or_generate_advice(
            crop=crop,
            location=location,
            country=country,
            prompt=prompt,
            not_found_message=f"Местото '{location}' не е пронајдено",
            lat=lat,
            lon=lon,
        )

        payload = extract_disease_info(
            advice_response=advice_response,
            crop=crop,
            location=location
        )
        payload["summary"] = _summarize_disease_payload(payload, crop, location)
        return payload

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
            not_found_message=f"Местото '{location}' не е пронајдено",
            lat=lat,
            lon=lon,
        )

        payload = extract_fertilizer_info(
            advice_response=advice_response,
            crop=crop,
            location=location,
            growth_stage=growth_stage
        )
        payload["summary"] = _summarize_fertilizer_payload(payload, crop, location)
        return payload

    if report_type == "Weather Analysis":
        service = WeatherService()
        if lat is not None and lon is not None:
            weather_data = service.get_weather_by_coords(lat, lon, location_name=location)
        else:
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
            not_found_message=f"Местото '{location}' не е пронајдено",
            lat=lat,
            lon=lon,
        )

        impacts = extract_weather_impacts(advice_response)

        payload = build_weather_dashboard_response(
            weather_data=weather_data,
            location=location,
            impacts=impacts
        )
        payload["summary"] = _summarize_weather_payload(payload, location)
        return payload

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
            not_found_message=f"Местото '{location}' не е пронајдено",
            lat=lat,
            lon=lon,
        )

        payload = _extract_irrigation_report_info(
            advice_response=advice_response,
            crop=crop,
            location=location
        )
        payload["summary"] = _summarize_irrigation_payload(payload, crop, location)
        return payload

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


def _safe_summary(summary_value):
    if not isinstance(summary_value, str):
        return None

    summary = summary_value.strip()
    if not summary:
        return None

    lowered = summary.lower()
    if lowered in {"no summary", "n/a", "none", "null", "unknown"}:
        return None

    return summary


def _first_dict(items):
    if not isinstance(items, list):
        return None

    for item in items:
        if isinstance(item, dict):
            return item

    return None


def _first_non_empty_text(*values):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def _find_metric_value(metrics, metric_label_fragment):
    if not isinstance(metrics, list):
        return None

    fragment = metric_label_fragment.lower()
    for item in metrics:
        if not isinstance(item, dict):
            continue

        label = item.get("label")
        if isinstance(label, str) and fragment in label.lower():
            value = item.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()

    return None


def _summarize_crop_analysis_payload(payload, crop, location):
    existing = _safe_summary(payload.get("summary"))
    if existing:
        return existing

    health = None
    health_data = payload.get("healthData") or payload.get("health_data")
    if isinstance(health_data, list):
        for item in health_data:
            if isinstance(item, dict):
                value = item.get("value")
                if isinstance(value, (int, float)):
                    health = value
                    break

    risk = None
    disease_risks = payload.get("diseaseRisks") or payload.get("disease_risks")
    if isinstance(disease_risks, list):
        max_risk = None
        for item in disease_risks:
            if not isinstance(item, dict):
                continue
            value = item.get("risk")
            if isinstance(value, (int, float)):
                max_risk = value if max_risk is None else max(max_risk, value)
        risk = max_risk

    recommendation_count = len(payload.get("recommendations") or [])
    return (
        f"{crop} at {location}: health index {health if health is not None else 'N/A'}/100, "
        f"peak disease risk {risk if risk is not None else 'N/A'}/100, "
        f"with {recommendation_count} recommended actions."
    )


def _summarize_disease_payload(payload, crop, location):
    existing = _safe_summary(payload.get("summary"))
    if existing:
        return existing

    alerts = payload.get("alerts") or payload.get("diseaseAlerts") or []
    first_alert = _first_dict(alerts)
    if first_alert:
        name = _first_non_empty_text(first_alert.get("name"), "disease risk")
        severity = _first_non_empty_text(first_alert.get("severity"), "Unknown")
        probability = first_alert.get("probability")
        if isinstance(probability, (int, float)):
            return (
                f"{crop} at {location}: highest immediate risk is {name} "
                f"({severity}, {probability}/100)."
            )
        return f"{crop} at {location}: highest immediate risk is {name} ({severity})."

    return f"{crop} at {location}: disease pressure assessment generated from current weather and forecast."


def _summarize_fertilizer_payload(payload, crop, location):
    existing = _safe_summary(payload.get("summary"))
    schedule = payload.get("schedule") or []
    metrics = payload.get("ai_metrics") or payload.get("aiMetrics") or []
    first_schedule = _first_dict(schedule)

    recommended_type = _find_metric_value(metrics, "recommended type")
    application_rate = _find_metric_value(metrics, "application rate")
    expected_yield = _find_metric_value(metrics, "yield")

    if not existing:
        existing = ""

    week = _first_non_empty_text(first_schedule.get("week") if first_schedule else None)
    fert_type = _first_non_empty_text(
        first_schedule.get("type") if first_schedule else None,
        recommended_type
    )
    rate = _first_non_empty_text(
        first_schedule.get("rate") if first_schedule else None,
        application_rate
    )

    details = []
    if fert_type:
        details.append(f"recommended fertilizer {fert_type}")
    if rate:
        details.append(f"at {rate}")
    if week:
        details.append(f"starting {week}")
    if expected_yield:
        details.append(f"expected yield impact {expected_yield}")

    if details:
        return f"{crop} at {location}: " + ", ".join(details) + "."

    return existing or f"{crop} at {location}: fertilizer plan generated from growth stage and weather forecast."


def _summarize_weather_payload(payload, location):
    existing = _safe_summary(payload.get("summary"))
    if existing:
        return existing

    current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    temperature = current.get("temperature")
    description = _first_non_empty_text(current.get("description"), "weather conditions")

    impacts = payload.get("impacts") or []
    top_impact = _first_dict(impacts)
    impact_text = None
    if top_impact:
        label = _first_non_empty_text(top_impact.get("label"), "Weather")
        level = _first_non_empty_text(top_impact.get("level"), "Unknown")
        impact_text = f"{label} impact is {level}"

    if isinstance(temperature, (int, float)):
        if impact_text:
            return f"{location}: {temperature}C with {description}; {impact_text}."
        return f"{location}: {temperature}C with {description}."

    if impact_text:
        return f"{location}: {impact_text} based on current conditions and 5-day forecast."

    return f"{location}: weather analysis generated from current conditions and 5-day forecast."


def _summarize_irrigation_payload(payload, crop, location):
    existing = _safe_summary(payload.get("summary"))
    if existing:
        return existing

    recs = payload.get("irrigation_recommendations") or []
    schedule = payload.get("schedule") or []
    first_rec = _first_dict(recs)
    first_slot = _first_dict(schedule)

    rec_title = _first_non_empty_text(first_rec.get("title") if first_rec else None)
    period = _first_non_empty_text(first_slot.get("period") if first_slot else None)
    action = _first_non_empty_text(first_slot.get("recommendation") if first_slot else None)

    parts = []
    if rec_title:
        parts.append(rec_title)
    if period and action:
        parts.append(f"{period}: {action}")

    if parts:
        return f"{crop} at {location}: " + " | ".join(parts)

    return f"{crop} at {location}: irrigation schedule generated from weather and crop needs."
