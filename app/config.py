import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', "dev-secret")

    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', "sqlite:///crop_advisor.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'super-jwt-secret')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
