from datetime import datetime, date
from app import db


class Field(db.Model):
    __tablename__ = 'fields'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    size = db.Column(db.Float, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    country = db.Column(db.String(10))
    crop_type = db.Column(db.String(100), nullable=False)
    soil_type = db.Column(db.String(100))
    irrigation_type = db.Column(db.String(100))
    notes = db.Column(db.Text)
    planting_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    size_unit = db.Column(db.String(20), default="acres")
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    crop_analyses = db.relationship('CropAnalysis', backref='field', lazy=True)
    weather_data = db.relationship('WeatherData', backref='field', lazy=True)
    reports = db.relationship('Report', backref='field', lazy=True)

    def _latest_analysis(self):
        if not self.crop_analyses:
            return None

        return max(
            self.crop_analyses,
            key=lambda analysis: analysis.created_at or datetime.min
        )

    def _analysis_value(self, analysis, *possible_fields):
        if not analysis:
            return None

        for field_name in possible_fields:
            value = getattr(analysis, field_name, None)

            if value is not None:
                return value

        return None

    def _last_analysis_label(self):
        latest_analysis = self._latest_analysis()

        if not latest_analysis:
            return "Never"

        latest = latest_analysis.created_at

        if not latest:
            return "Never"

        delta = datetime.utcnow() - latest
        days = delta.days

        if days <= 0:
            return "Today"

        if days == 1:
            return "1 day ago"

        if days < 7:
            return f"{days} days ago"

        weeks = days // 7
        return "1 week ago" if weeks == 1 else f"{weeks} weeks ago"

    def to_dict(self):
        latest_analysis = self._latest_analysis()

        health = self._analysis_value(
            latest_analysis,
            "health",
            "health_score",
            "score"
        )

        status = self._analysis_value(
            latest_analysis,
            "status",
            "health_status"
        )

        risk = self._analysis_value(
            latest_analysis,
            "risk",
            "risk_level"
        )

        planting_iso = (
            self.planting_date.isoformat()
            if isinstance(self.planting_date, (datetime, date))
            else None
        )

        coordinates = (
            {"lat": self.latitude, "lng": self.longitude}
            if self.latitude is not None and self.longitude is not None
            else None
        )

        return {
            "id": self.id,
            "name": self.name,
            "crop": self.crop_type,
            "location": self.location,
            "country": self.country,
            "size": f"{self.size:g} {self.size_unit or 'acres'}",

            "status": status,
            "lastAnalysis": self._last_analysis_label(),
            "health": health,
            "risk": risk,

            "soilType": self.soil_type,

            "sizeValue": self.size,
            "unit": self.size_unit or "acres",
            "coordinates": coordinates,
            "latitude": self.latitude,
            "longitude": self.longitude,

            "crop_type": self.crop_type,
            "soil_type": self.soil_type,
            "irrigation_type": self.irrigation_type,
            "irrigation": self.irrigation_type,

            "planting_date": planting_iso,
            "plantingDate": planting_iso,

            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "user_id": self.user_id,
        }