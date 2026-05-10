from datetime import datetime
from app import db

class CropAnalysis(db.Model):
    __tablename__ = 'crop_analyses'

    id = db.Column(db.Integer, primary_key=True)
    recommendation = db.Column(db.Text, nullable=False)
    health_score = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    
    field_id = db.Column(db.Integer, db.ForeignKey('fields.id'), nullable=False)