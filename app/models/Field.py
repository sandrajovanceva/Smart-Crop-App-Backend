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

    size_unit = db.Column(db.String(20), default="hectares")
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    crop_analyses = db.relationship('CropAnalysis', backref='field', lazy=True)
    weather_data = db.relationship('WeatherData', backref='field', lazy=True)
    reports = db.relationship('Report', backref='field', lazy=True)

    def _latest_crop_analysis_report(self):
        crop_reports = [r for r in (self.reports or []) if r.report_type == "Crop Analysis" and r.payload]
        if not crop_reports:
            return None
        return max(crop_reports, key=lambda r: r.created_at or datetime.min)

    def _latest_analysis(self):
        if self.crop_analyses:
            return max(
                self.crop_analyses,
                key=lambda analysis: analysis.created_at or datetime.min
            )
        return self._latest_crop_analysis_report()

    def _health_from_report(self):
        report = self._latest_crop_analysis_report()
        if report:
            payload = report.payload or {}
            health_data = payload.get("healthData") or payload.get("health_data") or []
            for item in health_data:
                if isinstance(item, dict) and isinstance(item.get("value"), (int, float)):
                    return item["value"]

        if self.crop_analyses:
            latest = max(self.crop_analyses, key=lambda a: a.created_at or datetime.min)
            if latest.health_score is not None:
                return latest.health_score

        return None

    def _risk_from_report(self):
        report = self._latest_crop_analysis_report()
        if not report:
            return None
        payload = report.payload or {}
        disease_risks = payload.get("diseaseRisks") or payload.get("disease_risks") or []
        values = [r["risk"] for r in disease_risks if isinstance(r, dict) and isinstance(r.get("risk"), (int, float))]
        return max(values) if values else None

    def _risk_level(self):
        risk = self._risk_from_report()
        if risk is None:
            return None
        if risk >= 70:
            return "High"
        if risk >= 40:
            return "Medium"
        return "Low"

    def _alerts_count_from_latest_weather(self):
        if not self.weather_data:
            return 0
        latest = max(self.weather_data, key=lambda w: w.recorded_at or datetime.min)
        count = 0
        temp = latest.temperature
        humidity = latest.humidity
        wind = latest.wind_speed
        if temp is not None and temp <= 2:
            count += 1
        if wind is not None and wind >= 10:
            count += 1
        if humidity is not None and temp is not None and humidity >= 85 and temp >= 15:
            count += 1
        return count

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
        health = self._health_from_report()
        risk = self._risk_level()
        status = None

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
            "size": f"{self.size:g} {self.size_unit or 'hectares'}",

            "status": status,
            "lastAnalysis": self._last_analysis_label(),
            "health": health,
            "risk": risk,

            "soilType": self.soil_type,

            "sizeValue": self.size,
            "unit": self.size_unit or "hectares",
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
            "alerts_count": self._alerts_count_from_latest_weather(),
        }
