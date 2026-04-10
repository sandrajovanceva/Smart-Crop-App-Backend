from app import db
from app.models.Field import Field
from datetime import datetime


def get_all_fields(user_id):
    fields = Field.query.filter_by(user_id=user_id).all()
    return [f.to_dict() for f in fields]


def get_field_by_id(field_id, user_id):
    field = Field.query.filter_by(id=field_id, user_id=user_id).first()
    if not field:
        return None, "Field not found"
    return field.to_dict(), None


def create_field(data, user_id):
    planting_date = None
    if data.get("planting_date"):
        try:
            planting_date = datetime.strptime(data["planting_date"], "%Y-%m-%d").date()
        except ValueError:
            return None, "Invalid date format. Use YYYY-MM-DD"

    field = Field(
        name=data["name"].strip(),
        size=data["size"],
        location=data["location"].strip(),
        crop_type=data["crop_type"].strip(),
        soil_type=data.get("soil_type"),
        irrigation_type=data.get("irrigation_type"),
        notes=data.get("notes"),
        planting_date=planting_date,
        user_id=user_id
    )

    db.session.add(field)
    db.session.commit()
    return field.to_dict(), None


def update_field(field_id, data, user_id):
    field = Field.query.filter_by(id=field_id, user_id=user_id).first()
    if not field:
        return None, "Field not found"

    if "name" in data:
        field.name = data["name"].strip()
    if "size" in data:
        if not isinstance(data["size"], (int, float)) or data["size"] <= 0:
            return None, "Size must be a positive number"
        field.size = data["size"]
    if "location" in data:
        field.location = data["location"].strip()
    if "crop_type" in data:
        field.crop_type = data["crop_type"].strip()
    if "soil_type" in data:
        field.soil_type = data["soil_type"]
    if "irrigation_type" in data:
        field.irrigation_type = data["irrigation_type"]
    if "notes" in data:
        field.notes = data["notes"]
    if "planting_date" in data:
        try:
            field.planting_date = datetime.strptime(data["planting_date"], "%Y-%m-%d").date()
        except ValueError:
            return None, "Invalid date format. Use YYYY-MM-DD"

    db.session.commit()
    return field.to_dict(), None


def delete_field(field_id, user_id):
    field = Field.query.filter_by(id=field_id, user_id=user_id).first()
    if not field:
        return False, "Field not found"

    db.session.delete(field)
    db.session.commit()
    return True, None