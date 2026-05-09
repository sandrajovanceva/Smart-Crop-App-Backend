from app.errors import BadRequestError, NotFoundError
from app.models.Field import Field


def resolve_crop_location(data, user_id):
    field_id = data.get("field_id") or data.get("fieldId")

    if field_id:
        field = Field.query.filter_by(id=field_id, user_id=user_id).first()

        if not field:
            raise NotFoundError("Field not found")

        country = data.get("country") or field.country
        return field.crop_type, field.location, country, field.latitude, field.longitude

    crop = data.get("crop")
    location = data.get("location")
    country = data.get("country")

    if not crop or not location:
        raise BadRequestError("Missing required fields: crop, location or field_id")

    return crop, location, country, None, None
