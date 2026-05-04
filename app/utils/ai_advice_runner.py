from app.errors import NotFoundError, ExternalServiceError
from app.services.ai_service import AIService
from app.services.cache_service import CacheService
from app.services.weather_service import WeatherService


def get_cached_or_generate_advice(
        crop,
        location,
        country,
        prompt,
        not_found_message=None,
        weather_data=None
):
    cached = CacheService.get_cached_advice(
        crop=crop,
        location=location,
        country=country,
        question=prompt
    )

    if cached:
        return cached

    if weather_data is None:
        weather_service = WeatherService()
        weather_data = weather_service.get_weather_by_location(location, country)

    if not weather_data:
        raise NotFoundError(not_found_message or f"Location '{location}' not found")

    ai_service = AIService()

    try:
        advice = ai_service.get_crop_advice(
            crop_name=crop,
            weather_data=weather_data,
            user_question=prompt
        )
    except ExternalServiceError:
        return {
            "weather": weather_data,
            "advice": {},
            "from_cache": False,
            "ai_unavailable": True,
        }

    response_data = {
        "weather": weather_data,
        "advice": advice,
        "from_cache": False,
        "ai_unavailable": False,
    }

    CacheService.save_advice(
        crop=crop,
        location=location,
        country=country,
        response_data=response_data,
        question=prompt
    )

    return response_data
