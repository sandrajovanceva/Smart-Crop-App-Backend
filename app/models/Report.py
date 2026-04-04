from datetime import datetime
from app import db

class Report(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)   
    report_type = db.Column(db.String(50))              
    file_path = db.Column(db.String(500))               
    file_size = db.Column(db.Float)                     
    status = db.Column(db.String(50), default='completed')  
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    
    field_id = db.Column(db.Integer, db.ForeignKey('fields.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)