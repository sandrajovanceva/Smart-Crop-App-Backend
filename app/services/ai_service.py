import json
import os
import re

from flask import current_app
from openai import OpenAI

from app.errors import ConfigurationError, ExternalServiceError


class AIService:
    """AI сервис со Fallback архитектура: Примарно Gemini, Секундарно Groq."""

    GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
    GROQ_BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self):
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        if not self.gemini_key:
            raise ConfigurationError("GEMINI_API_KEY не е поставен")

        self.gemini_client = OpenAI(api_key=self.gemini_key, base_url=self.GEMINI_BASE_URL)
        self.gemini_model = "gemini-2.0-flash"

        self.groq_key = os.getenv("GROQ_API_KEY")
        self.groq_client = None
        if self.groq_key:
            self.groq_client = OpenAI(api_key=self.groq_key, base_url=self.GROQ_BASE_URL)

        self.groq_model = "llama-3.3-70b-versatile"

    def get_crop_advice(self, crop_name, weather_data, user_question=None):
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(crop_name, weather_data, user_question)

        try:
            return self._call_gemini(crop_name, system_prompt, user_prompt, user_question)

        except Exception as e:
            current_app.logger.warning(
                f"Gemini дефект: {str(e)}. Префрлам на Groq Fallback...",
                extra={"event": "ai_service.switching_to_groq"}
            )

            if self.groq_client:
                try:
                    return self._call_groq(crop_name, system_prompt, user_prompt, user_question)
                except Exception as ge:
                    current_app.logger.error(f"И Groq не успеа: {ge}")
                    raise ExternalServiceError("Сите AI сервиси се недостапни.")
            else:
                raise ExternalServiceError("Gemini е блокиран, а Groq не е конфигуриран во .env")

    def _call_gemini(self, crop_name, system_prompt, user_prompt, user_question):
        response = self.gemini_client.chat.completions.create(
            model=self.gemini_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        if not raw or raw.strip() == "":
            raise ValueError("Празен одговор од Gemini")

        advice = self._extract_json(raw)
        return self._format_final_response(crop_name, advice, self.gemini_model, response.usage.total_tokens,
                                           user_question)

    def _call_groq(self, crop_name, system_prompt, user_prompt, user_question):
        response = self.groq_client.chat.completions.create(
            model=self.groq_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            response_format={"type": "json_object"}
        )

        raw = response.choices[0].message.content
        advice = self._extract_json(raw)
        tokens = response.usage.total_tokens if response.usage else 0

        return self._format_final_response(crop_name, advice, self.groq_model, tokens, user_question)

    @staticmethod
    def _format_final_response(crop, advice, model, tokens, has_q):
        current_app.logger.info(f"Успешно генериран совет преку моделот: {model}")
        return {
            "crop": crop,
            "advice": advice,
            "model_used": model,
            "tokens_used": tokens,
            "has_user_question": bool(has_q)
        }

    @staticmethod
    def _extract_json(text):
        try:
            text = text.strip()
            markdown_match = re.search(r'```(?:json)?\s*({.*?})\s*```', text, re.DOTALL)
            if markdown_match:
                return json.loads(markdown_match.group(1))

            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                return json.loads(text[start:end + 1])

            return json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            current_app.logger.error(f"JSON Parsing Error: {str(e)} | Raw text: {text[:100]}")
            return None

    @staticmethod
    def _build_system_prompt():
        return """You are an expert in agriculture and agronomy. You provide concrete, practical
                    advice to farmers based on weather conditions and crop type.

                    RULES:
                    - Write ONLY in English
                    - Be specific - reference real numbers from the weather data
                    - Give advice for THE NEXT 5 DAYS
                    - If there is a risk (frost, heavy rain, strong wind) - highlight it as a priority

                    CRITICAL: Respond ONLY with a valid JSON object, no additional text,
                    no markdown code blocks, no explanations before or after the JSON.

                    STRICT JSON FORMAT:
                    {
                      "summary": "short overview in 1-2 sentences",
                      "immediate_actions": ["action 1", "action 2"],
                      "warnings": ["warning 1"],
                      "irrigation_advice": "irrigation recommendation",
                      "pest_disease_risk": "disease and pest risk assessment",
                      "recommended_activities": ["recommendation 1", "recommendation 2"],
                      "activities_to_avoid": ["avoid 1", "avoid 2"]
                    }"""

    @staticmethod
    def _build_user_prompt(crop_name, weather_data, user_question):
        current = weather_data.get("current", {})
        forecast = weather_data.get("forecast_5_days", [])
        alerts = weather_data.get("agricultural_alerts", [])
        location = weather_data.get("location", {})

        prompt = f"""CROP: {crop_name}
                    LOCATION: {location.get('found_name', 'unknown')}

                    CURRENT CONDITIONS:
                    - Temperature: {current.get('temperature')}°C (feels like {current.get('feels_like')}°C)
                    - Humidity: {current.get('humidity')}%
                    - Wind: {current.get('wind_speed')} m/s
                    - Description: {current.get('description')}
                    - Rain last hour: {current.get('rain_1h_mm')} mm

                    5-DAY FORECAST:
                    """
        for day in forecast:
            prompt += (
                f"- {day['date']}: {day['temp_min']}°C to {day['temp_max']}°C, "
                f"rain probability {day['rain_probability']}%, "
                f"rainfall {day['total_rain_mm']}mm, "
                f"wind up to {day['wind_max']}m/s, "
                f"{day['description']}\n"
            )

        if alerts:
            prompt += "\nAUTOMATIC ALERTS:\n"
            for alert in alerts:
                prompt += f"- [{alert['severity'].upper()}] {alert['message']}\n"

        if user_question:
            prompt += f"\nUSER QUESTION: {user_question}\n"

        prompt += "\nReturn the response ONLY in JSON format as defined. No markdown, no extra text."
        return prompt
