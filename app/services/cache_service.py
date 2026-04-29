from datetime import datetime, timedelta
from flask import current_app

from app import db
from app.models.AdviceCache import AdviceCache


class CacheService:
    """Сервис за кеширање на AI совети."""

    CACHE_DURATION_HOURS = 2

    @staticmethod
    def _normalize_text(value):
        """Нормализира текст за конзистентно пребарување во кеш."""

        if not value:
            return None

        return " ".join(value.strip().lower().split())

    @classmethod
    def get_cached_advice(cls, crop, location, country="MK", question=None):
        """Враќа свеж кеширан совет ако постои, инаку None."""
        current_app.logger.info(
            "get cached advice service started",
            extra={
                "class_name": cls.__name__,
                "event": "cache_service.get_cached_advice_started",
                "crop": crop,
                "location": location,
                "country": country,
                "has_question": bool(question)
            }
        )

        normalized_crop = cls._normalize_text(crop)
        normalized_location = cls._normalize_text(location)
        normalized_country = country.strip().upper()
        normalized_question = cls._normalize_text(question)

        cutoff_time = datetime.utcnow() - timedelta(hours=cls.CACHE_DURATION_HOURS)

        query = AdviceCache.query.filter(
            AdviceCache.crop == normalized_crop,
            AdviceCache.location == normalized_location,
            AdviceCache.country == normalized_country,
            AdviceCache.created_at >= cutoff_time,
        )

        if normalized_question is None:
            query = query.filter(AdviceCache.question.is_(None))
        else:
            query = query.filter(AdviceCache.question == normalized_question)

        cache_entry = query.order_by(AdviceCache.created_at.desc()).first()

        if cache_entry:
            age_minutes = (datetime.utcnow() - cache_entry.created_at).total_seconds() / 60
            current_app.logger.info(
                "advice cache hit",
                extra={
                    "class_name": cls.__name__,
                    "event": "cache_service.cache_hit",
                    "crop": normalized_crop,
                    "location": normalized_location,
                    "country": normalized_country,
                    "has_question": normalized_question is not None,
                    "age_minutes": round(age_minutes)
                }
            )
            return cache_entry.response_data

        current_app.logger.info(
            "advice cache miss",
            extra={
                "class_name": cls.__name__,
                "event": "cache_service.cache_miss",
                "crop": normalized_crop,
                "location": normalized_location,
                "country": normalized_country,
                "has_question": normalized_question is not None
            }
        )
        return None

    @classmethod
    def save_advice(cls, crop, location, response_data, country="MK", question=None):
        """Зачувува нов совет во кеш."""
        current_app.logger.info(
            "save advice cache service started",
            extra={
                "class_name": cls.__name__,
                "event": "cache_service.save_advice_started",
                "crop": crop,
                "location": location,
                "country": country,
                "has_question": bool(question)
            }
        )

        normalized_crop = cls._normalize_text(crop)
        normalized_location = cls._normalize_text(location)
        normalized_country = country.strip().upper()
        normalized_question = cls._normalize_text(question)

        try:
            cache_entry = AdviceCache(
                crop=normalized_crop,
                location=normalized_location,
                country=normalized_country,
                question=normalized_question,
                response_data=response_data,
            )
            db.session.add(cache_entry)
            db.session.commit()

            current_app.logger.info(
                "advice cache saved",
                extra={
                    "class_name": cls.__name__,
                    "event": "cache_service.cache_saved",
                    "crop": normalized_crop,
                    "location": normalized_location,
                    "country": normalized_country,
                    "has_question": normalized_question is not None
                }
            )
            return cache_entry

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Cache save error: {e}",
                extra={"class_name": cls.__name__, "event": "cache_service.cache_save_failed"}
            )
            return None

    @classmethod
    def cleanup_old_entries(cls, days=7):
        """Брише записи од кеш постари од зададен број денови."""
        current_app.logger.info(
            "cleanup advice cache service started",
            extra={"class_name": cls.__name__, "event": "cache_service.cleanup_started", "days": days}
        )

        cutoff_time = datetime.utcnow() - timedelta(days=days)
        deleted = AdviceCache.query.filter(
            AdviceCache.created_at < cutoff_time
        ).delete()
        db.session.commit()

        current_app.logger.info(
            f"Deleted {deleted} old cache entries",
            extra={"class_name": cls.__name__, "event": "cache_service.cleanup_completed", "deleted": deleted}
        )
        return deleted
