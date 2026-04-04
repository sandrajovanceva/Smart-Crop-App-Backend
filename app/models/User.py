from datetime import datetime
from app import db

class User(db.Model):
    __tablename__ = 'users'


    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    fields = db.relationship('Field', backref='user', lazy=True)
    reports = db.relationship('Report', backref='user', lazy=True)