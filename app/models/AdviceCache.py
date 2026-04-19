from datetime import datetime
from app import db


class AdviceCache(db.Model):
    """Модел за кеширање на AI совети."""

    __tablename__ = "advice_cache"

    id = db.Column(db.Integer, primary_key=True)
    crop = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    country = db.Column(db.String(10), nullable=False, default="MK")
    question = db.Column(db.Text, nullable=True)
    response_data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<AdviceCache {self.crop}@{self.location} q={self.question}>"