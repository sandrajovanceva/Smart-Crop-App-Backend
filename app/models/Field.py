from datetime import datetime
from app import db

class Field(db.Model):
    __tablename__ = 'fields'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    size = db.Column(db.Float, nullable=False)  # во хектари
    location = db.Column(db.String(200), nullable=False)
    crop_type = db.Column(db.String(100), nullable=False)
    soil_type = db.Column(db.String(100))
    irrigation_type = db.Column(db.String(100))
    notes = db.Column(db.Text)
    planting_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    crop_analyses = db.relationship('CropAnalysis', backref='field', lazy=True)
    weather_data = db.relationship('WeatherData', backref='field', lazy=True)
    reports = db.relationship('Report', backref='field', lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "size": self.size,
            "location": self.location,
            "crop_type": self.crop_type,
            "soil_type": self.soil_type,
            "irrigation_type": self.irrigation_type,
            "notes": self.notes,
            "planting_date": self.planting_date.isoformat() if self.planting_date else None,
            "created_at": self.created_at.isoformat(),
            "user_id": self.user_id
        }