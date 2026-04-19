import os
import json
import re
from openai import OpenAI
from flask import current_app


class AIService:
    """AI сервис за земјоделски совети - користи Google Gemini API."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY не е поставен во .env фајлот")

        self.client = OpenAI(
            api_key=api_key,
            base_url=self.BASE_URL,
        )
        self.model = "gemini-2.5-flash"

    def get_crop_advice(self, crop_name, weather_data, user_question=None):
        """Генерира AI совет за дадена култура врз основа на временски податоци добиени од OpenWeather API."""

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(crop_name, weather_data, user_question)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.4,
                max_tokens=4000,
            )

            raw = response.choices[0].message.content
            current_app.logger.info(f"AI raw response: {raw[:500]}")

            advice = self._extract_json(raw)

            return {
                "crop": crop_name,
                "advice": advice,
                "model_used": self.model,
                "tokens_used": response.usage.total_tokens if response.usage else None,
            }

        except json.JSONDecodeError as e:
            current_app.logger.error(f"AI response not valid JSON: {e}")
            current_app.logger.error(f"Raw response was: {raw}")
            raise ValueError(f"AI моделот не врати валиден JSON одговор. Raw: {raw[:200]}")
        except Exception as e:
            current_app.logger.error(f"AI service error: {e}")
            raise

    @staticmethod
    def _extract_json(text):
        """Екстрактира JSON од одговор кој може да има markdown формат или extra текст."""

        text = text.strip()

        markdown_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if markdown_match:
            return json.loads(markdown_match.group(1))

        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])

        return json.loads(text)

    @staticmethod
    def _build_system_prompt():
        return """Ти си експерт за земјоделство и агрономија. Даваш конкретни, практични 
                    совети на фармери врз основа на временските услови и културата.
                    
                    ПРАВИЛА:
                    - Пиши САМО на македонски јазик
                    - Биди конкретен - спомнувај реални бројки од временските податоци
                    - Давај совети за СЛЕДНИТЕ 5 ДЕНА
                    - Ако има ризик (мраз, обилен дожд, силен ветер) - истакни го приоритетно
                    
                    КРИТИЧНО ВАЖНО: Одговараш САМО со валиден JSON објект, без никаков дополнителен текст, 
                    без markdown кодни блокови, без објаснувања пред или после JSON-от.
                    
                    СТРИКТЕН JSON ФОРМАТ:
                    {
                      "summary": "краток преглед во 1-2 реченици",
                      "immediate_actions": ["активност 1", "активност 2"],
                      "warnings": ["предупредување 1"],
                      "irrigation_advice": "совет за наводнување",
                      "pest_disease_risk": "проценка на ризик од болести",
                      "recommended_activities": ["препорачано 1", "препорачано 2"],
                      "activities_to_avoid": ["избегнувај 1", "избегнувај 2"]
                    }"""

    @staticmethod
    def _build_user_prompt(crop_name, weather_data, user_question):
        current = weather_data.get("current", {})
        forecast = weather_data.get("forecast_5_days", [])
        alerts = weather_data.get("agricultural_alerts", [])
        location = weather_data.get("location", {})

        prompt = f"""КУЛТУРА: {crop_name}
                    ЛОКАЦИЈА: {location.get('found_name', 'непознато')}
                    
                    ТЕКОВНИ УСЛОВИ:
                    - Температура: {current.get('temperature')}°C (се чувствува како {current.get('feels_like')}°C)
                    - Влажност: {current.get('humidity')}%
                    - Ветер: {current.get('wind_speed')} m/s
                    - Опис: {current.get('description')}
                    - Дожд последен час: {current.get('rain_1h_mm')} mm
                    
                    ПРОГНОЗА ЗА СЛЕДНИТЕ 5 ДЕНА:
                    """
        for day in forecast:
            prompt += (
                f"- {day['date']}: {day['temp_min']}°C до {day['temp_max']}°C, "
                f"веројатност за дожд {day['rain_probability']}%, "
                f"врнежи {day['total_rain_mm']}mm, "
                f"ветер до {day['wind_max']}m/s, "
                f"{day['description']}\n"
            )

        if alerts:
            prompt += "\nАВТОМАТСКИ СИГНАЛИ:\n"
            for alert in alerts:
                prompt += f"- [{alert['severity'].upper()}] {alert['message']}\n"

        if user_question:
            prompt += f"\nКОНКРЕТНО ПРАШАЊЕ ОД КОРИСНИКОТ: {user_question}\n"

        prompt += "\nВрати ОДГОВОР САМО во JSON формат според дефинираната структура. Без markdown, без extra текст."
        return prompt
