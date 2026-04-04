from datetime import datetime
from app import db

class WeatherData(db.Model):
    __tablename__ = 'weather_data'

    id = db.Column(db.Integer, primary_key=True)
    temperature = db.Column(db.Float)        
    humidity = db.Column(db.Float)           
    rainfall = db.Column(db.Float)          
    wind_speed = db.Column(db.Float)         
    description = db.Column(db.String(200))  
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)

    
    field_id = db.Column(db.Integer, db.ForeignKey('fields.id'), nullable=False)