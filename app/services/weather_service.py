import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from flask import current_app

from app.errors import ConfigurationError, ExternalServiceError


class WeatherService:
    BASE_URL = "https://api.openweathermap.org/data/2.5"
    GEO_URL = "https://api.openweathermap.org/geo/1.0"

    _weather_cache: dict = {}
    _weather_cache_lock = threading.Lock()
    _WEATHER_CACHE_MINUTES = 15

    @classmethod
    def _cache_key(cls, lat, lon):
        return (round(float(lat), 2), round(float(lon), 2))

    @classmethod
    def _get_from_cache(cls, lat, lon):
        key = cls._cache_key(lat, lon)
        with cls._weather_cache_lock:
            entry = cls._weather_cache.get(key)
        if entry:
            ts, data = entry
            if time.time() - ts < cls._WEATHER_CACHE_MINUTES * 60:
                return data
        return None

    @classmethod
    def _set_in_cache(cls, lat, lon, data):
        key = cls._cache_key(lat, lon)
        with cls._weather_cache_lock:
            cls._weather_cache[key] = (time.time(), data)

    def _fetch_parallel(self, lat, lon):
        app = current_app._get_current_object()

        def with_ctx(fn, *args):
            with app.app_context():
                return fn(*args)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f_current = executor.submit(with_ctx, self._fetch_current, lat, lon)
            f_forecast = executor.submit(with_ctx, self._fetch_forecast, lat, lon)
            return f_current.result(), f_forecast.result()

    def __init__(self):
        self.api_key = os.getenv("WEATHER_API_KEY")
        if not self.api_key:
            raise ConfigurationError("WEATHER_API_KEY не е поставен во .env фајлот")

    def get_weather_by_coords(self, lat, lon, location_name=None):
        cached = self._get_from_cache(lat, lon)
        if cached:
            current_app.logger.info(
                "weather cache hit",
                extra={"event": "weather_service.cache_hit", "lat": lat, "lon": lon}
            )
            return cached

        current, forecast = self._fetch_parallel(lat, lon)

        result = {
            "location": {
                "searched_name": location_name,
                "found_name": current.get("name") or location_name,
                "country": (current.get("sys") or {}).get("country"),
                "region": None,
                "lat": lat,
                "lon": lon,
            },
            "current": self._format_current(current),
            "forecast_5_days": self._format_forecast(forecast),
            "forecast_24h": self._format_24h(forecast),
            "agricultural_alerts": self._build_alerts(current, forecast),
        }
        self._set_in_cache(lat, lon, result)
        return result

    def get_weather_by_location(self, location_name, country_code=None):
        current_app.logger.info(
            "get weather by location service started",
            extra={
                "class_name": self.__class__.__name__,
                "event": "weather_service.get_by_location_started",
                "location": location_name,
                "country": country_code
            }
        )

        coords = self._geocode(location_name, country_code)
        if not coords:
            return None

        lat = coords["lat"]
        lon = coords["lon"]

        cached = self._get_from_cache(lat, lon)
        if cached:
            current_app.logger.info(
                "weather cache hit",
                extra={"event": "weather_service.cache_hit", "location": location_name}
            )
            return cached

        current, forecast = self._fetch_parallel(lat, lon)

        result = {
            "location": {
                "searched_name": location_name,
                "found_name": coords["name"],
                "country": coords.get("country"),
                "region": coords.get("state"),
                "lat": lat,
                "lon": lon,
            },
            "current": self._format_current(current),
            "forecast_5_days": self._format_forecast(forecast),
            "forecast_24h": self._format_24h(forecast),
            "agricultural_alerts": self._build_alerts(current, forecast),
        }
        self._set_in_cache(lat, lon, result)
        return result

    def search_locations(self, query, country_code=None, limit=5):
        current_app.logger.info(
            "search weather locations service started",
            extra={
                "class_name": self.__class__.__name__,
                "event": "weather_service.search_locations_started",
                "query": query,
                "country": country_code,
                "limit": limit
            }
        )

        params = {"q": query, "limit": limit, "appid": self.api_key}
        if country_code and country_code.strip():
            params["q"] = f"{query},{country_code.strip().upper()}"
        try:
            r = requests.get(f"{self.GEO_URL}/direct", params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            return [
                {
                    "name": item["name"],
                    "country": item.get("country"),
                    "state": item.get("state"),
                    "lat": item["lat"],
                    "lon": item["lon"],
                }
                for item in data
            ]
        except requests.RequestException as e:
            current_app.logger.error(
                f"Geocoding search error: {e}",
                extra={
                    "class_name": self.__class__.__name__,
                    "event": "weather_service.geocoding_search_failed",
                    "query": query,
                    "country": country_code
                }
            )
            raise ExternalServiceError("Не може да се пребараат временски локации") from e

    _STRIP_PREFIXES = ("city of ", "municipality of ")
    _STRIP_SUFFIXES = (
        " district", " region", " oblast", " province", " county",
        " municipality", " okrug", " rayon", " municipal district",
        " муниципальный округ", " муниципальный район",
        " городской округ", " район", " область", " край", " округ",
    )

    def _geocode(self, location_name, country_code):
        queries = []
        if location_name and isinstance(location_name, str):
            raw_name = location_name.strip()
            if raw_name:
                queries.append(raw_name)

                lowered = raw_name.lower()
                for prefix in self._STRIP_PREFIXES:
                    if lowered.startswith(prefix):
                        simplified = raw_name[len(prefix):].strip()
                        if simplified:
                            queries.append(simplified)
                        break

                for suffix in self._STRIP_SUFFIXES:
                    if lowered.endswith(suffix):
                        simplified = raw_name[: len(raw_name) - len(suffix)].strip()
                        if simplified:
                            queries.append(simplified)
                        break

                first_word = raw_name.split()[0]
                if first_word not in queries:
                    queries.append(first_word)

        if not queries:
            return None

        country = country_code.strip().upper() if isinstance(country_code, str) and country_code.strip() else None

        query_candidates = []
        for query in queries:
            if country:
                query_candidates.append(f"{query},{country}")
            query_candidates.append(query)

        for query in query_candidates:
            result = self._geocode_direct(query)
            if result:
                return result

        return None

    def country_from_coords(self, lat, lon):
        params = {"lat": lat, "lon": lon, "limit": 1, "appid": self.api_key}
        try:
            r = requests.get(f"{self.GEO_URL}/reverse", params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            if data:
                return data[0].get("country")
        except requests.RequestException as e:
            current_app.logger.warning(
                f"Reverse geocoding failed: {e}",
                extra={
                    "class_name": self.__class__.__name__,
                    "event": "weather_service.reverse_geocoding_failed",
                    "lat": lat,
                    "lon": lon,
                }
            )
        return None

    def _geocode_direct(self, query):
        params = {"q": query, "limit": 1, "appid": self.api_key}
        try:
            r = requests.get(f"{self.GEO_URL}/direct", params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            current_app.logger.error(
                f"Geocoding error: {e}",
                extra={
                    "class_name": self.__class__.__name__,
                    "event": "weather_service.geocoding_failed",
                    "query": query
                }
            )
            raise ExternalServiceError("Не може да се добијат координати од временскиот сервис") from e

        if not data:
            return None

        return {
            "lat": data[0]["lat"],
            "lon": data[0]["lon"],
            "name": data[0]["name"],
            "country": data[0].get("country"),
            "state": data[0].get("state"),
        }

    def _fetch_current(self, lat, lon):
        return self._request("weather", {"lat": lat, "lon": lon})

    def _fetch_forecast(self, lat, lon):
        return self._request("forecast", {"lat": lat, "lon": lon})

    def _request(self, endpoint, params):
        params["appid"] = self.api_key
        params["units"] = "metric"
        params["lang"] = "en"
        started_at = time.perf_counter()
        try:
            r = requests.get(f"{self.BASE_URL}/{endpoint}", params=params, timeout=10)
            r.raise_for_status()
            current_app.logger.info(
                "weather provider request completed",
                extra={
                    "class_name": self.__class__.__name__,
                    "event": "weather.provider_request_completed",
                    "provider": "openweathermap",
                    "endpoint": endpoint,
                    "status_code": r.status_code,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2)
                }
            )
            return r.json()
        except requests.RequestException as e:
            current_app.logger.error(
                "Weather request error",
                extra={
                    "class_name": self.__class__.__name__,
                    "event": "weather.provider_request_failed",
                    "provider": "openweathermap",
                    "endpoint": endpoint,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2)
                }
            )
            raise ExternalServiceError("Не може да се добијат временски податоци") from e

    @staticmethod
    def _format_current(data):
        return {
            "temperature": data["main"]["temp"],
            "feels_like": data["main"]["feels_like"],
            "temp_min": data["main"]["temp_min"],
            "temp_max": data["main"]["temp_max"],
            "humidity": data["main"]["humidity"],
            "pressure": data["main"]["pressure"],
            "description": data["weather"][0]["description"],
            "main": data["weather"][0]["main"],
            "icon": data["weather"][0]["icon"],
            "wind_speed": data["wind"]["speed"],
            "wind_speed_kmh": round(data["wind"]["speed"] * 3.6, 1),
            "clouds_percent": data.get("clouds", {}).get("all", 0),
            "rain_1h_mm": data.get("rain", {}).get("1h", 0),
            "timestamp": datetime.fromtimestamp(data["dt"]).isoformat(),
            "visibility": round(data.get("visibility", 0) / 1000, 1) if data.get("visibility") is not None else None,
        }

    @staticmethod
    def _format_24h(data):
        result = []
        for item in data["list"][:8]:
            result.append({
                "time": datetime.fromtimestamp(item["dt"]).strftime("%H:%M"),
                "temp": round(item["main"]["temp"], 1),
                "humidity": item["main"]["humidity"],
                "rain_3h": round(item.get("rain", {}).get("3h", 0), 2),
            })
        return result

    @staticmethod
    def _format_forecast(data):
        daily = defaultdict(list)
        for item in data["list"]:
            date = datetime.fromtimestamp(item["dt"]).strftime("%Y-%m-%d")
            daily[date].append(item)

        result = []
        for date, items in list(daily.items())[:5]:
            temps = [i["main"]["temp"] for i in items]
            humidities = [i["main"]["humidity"] for i in items]
            rains = [i.get("rain", {}).get("3h", 0) for i in items]
            pops = [i.get("pop", 0) for i in items]
            winds = [i["wind"]["speed"] for i in items]
            d = datetime.strptime(date, "%Y-%m-%d")
            display_date = f"{d.strftime('%B')} {d.day}"

            result.append({
                "date": display_date,
                "temp_min": round(min(temps), 1),
                "temp_max": round(max(temps), 1),
                "temp_avg": round(sum(temps) / len(temps), 1),
                "humidity_avg": round(sum(humidities) / len(humidities)),
                "total_rain_mm": round(sum(rains), 2),
                "rain_probability": round(max(pops) * 100),
                "wind_max": round(max(winds), 1),
                "description": items[len(items) // 2]["weather"][0]["description"],
            })

        return result

    @staticmethod
    def _build_alerts(current_data, forecast_data):
        alerts = []

        current_temp = current_data["main"]["temp"]
        current_humidity = current_data["main"]["humidity"]
        current_wind = current_data["wind"]["speed"]

        if current_temp <= 2:
            alerts.append({
                "severity": "high",
                "type": "frost_risk",
                "message": "Very low temperature - frost risk for sensitive crops"
            })
        if current_wind >= 10:
            alerts.append({
                "severity": "medium",
                "type": "strong_wind",
                "message": "Strong wind - spraying not recommended"
            })
        if current_humidity >= 85 and current_temp >= 15:
            alerts.append({
                "severity": "medium",
                "type": "fungal_risk",
                "message": "High humidity and warm weather - risk of fungal diseases"
            })

        frost_days = []
        heavy_rain_days = []
        for item in forecast_data["list"]:
            date = datetime.fromtimestamp(item["dt"]).strftime("%Y-%m-%d")
            if item["main"]["temp_min"] <= 2 and date not in frost_days:
                frost_days.append(date)
            rain_3h = item.get("rain", {}).get("3h", 0)
            if rain_3h >= 10 and date not in heavy_rain_days:
                heavy_rain_days.append(date)

        def _fmt(d_str):
            d = datetime.strptime(d_str, "%Y-%m-%d")
            return f"{d.strftime('%B')} {d.day}"

        if frost_days:
            formatted_frost = [_fmt(d) for d in frost_days]
            alerts.append({
                "severity": "high",
                "type": "upcoming_frost",
                "message": f"Possible frost on the following days: {', '.join(formatted_frost)}",
                "dates": formatted_frost,
            })
        if heavy_rain_days:
            formatted_rain = [_fmt(d) for d in heavy_rain_days]
            alerts.append({
                "severity": "medium",
                "type": "heavy_rain",
                "message": f"Expected heavy rainfall: {', '.join(formatted_rain)}",
                "dates": formatted_rain,
            })

        return alerts
