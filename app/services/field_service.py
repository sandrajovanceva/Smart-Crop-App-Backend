import csv
import io
from datetime import datetime

import requests
from flask import current_app

from app import db
from app.errors import BadRequestError, NotFoundError
from app.models.Crop_analysis import CropAnalysis
from app.models.Field import Field
from app.models.Report import Report
from app.models.Weather_data import WeatherData
from app.utils.validators import validate_field_input

REQUIRED_CSV_COLUMNS = ["name", "size", "location", "crop_type"]
OPTIONAL_CSV_COLUMNS = [
    "soil_type",
    "irrigation_type",
    "notes",
    "planting_date",
    "size_unit",
    "coordinates",
    "latitude",
    "longitude",
]
CSV_COLUMNS = REQUIRED_CSV_COLUMNS + OPTIONAL_CSV_COLUMNS


def get_all_fields(user_id):
    current_app.logger.info(
        "get all fields service started",
        extra={"event": "field_service.get_all_started", "owner_user_id": user_id}
    )

    fields = Field.query.filter_by(user_id=user_id).all()
    return [f.to_dict() for f in fields]


def get_field_by_id(field_id, user_id):
    current_app.logger.info(
        "get field by id service started",
        extra={"event": "field_service.get_by_id_started", "field_id": field_id, "owner_user_id": user_id}
    )

    field = Field.query.filter_by(id=field_id, user_id=user_id).first()
    if not field:
        raise NotFoundError("Field not found")
    return field.to_dict()


def reverse_geocode(lat, lon):
    if lat is None or lon is None:
        return None

    try:
        app_name = current_app.config.get("APP_NAME", "SmartCrop")
        contact_email = current_app.config.get("CONTACT_EMAIL", "support@smartcrop.local")
        headers = {
            "User-Agent": f"{app_name}/1.0 ({contact_email})"
        }
        params = {
            "lat": lat,
            "lon": lon,
            "format": "json",
            "addressdetails": 1,
            "zoom": 10,
            "accept-language": "en",
        }
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            headers=headers,
            params=params,
            timeout=5
        )
        resp.raise_for_status()
        data = resp.json()
        address = data.get("address") or {}

        location_name = _extract_location_name(address)
        if location_name:
            return location_name

        display_name = data.get("display_name")
        if isinstance(display_name, str) and display_name.strip():
            return display_name.strip()

        return None
    except (requests.RequestException, ValueError):
        return None


def resolve_location_from_coordinates(latitude, longitude):
    latitude = _coerce_coordinate(latitude, "Latitude", -90, 90)
    longitude = _coerce_coordinate(longitude, "Longitude", -180, 180)

    if latitude is None or longitude is None:
        raise BadRequestError("Latitude and longitude are required")

    reverse_geocoded = reverse_geocode(latitude, longitude)
    if reverse_geocoded and reverse_geocoded.strip():
        return reverse_geocoded.strip()

    raise BadRequestError("Could not resolve location name from coordinates")


def create_field(data, user_id):
    current_app.logger.info(
        "create field service started",
        extra={
            "event": "field_service.create_started",
            "owner_user_id": user_id,
            "body_fields": list(data.keys()) if isinstance(data, dict) else []
        }
    )

    if not isinstance(data, dict):
        raise BadRequestError("Invalid request body")

    valid, error = validate_field_input(data)
    if not valid:
        raise BadRequestError(error)

    planting_date = _parse_planting_date(data.get("planting_date"))

    field = _create_field_model(data, user_id, planting_date)

    db.session.add(field)
    db.session.commit()

    return field.to_dict()


def update_field(field_id, data, user_id):
    current_app.logger.info(
        "update field service started",
        extra={
            "event": "field_service.update_started",
            "field_id": field_id,
            "owner_user_id": user_id,
            "body_fields": list(data.keys()) if isinstance(data, dict) else []
        }
    )

    if not isinstance(data, dict):
        raise BadRequestError("Invalid request body")

    field = Field.query.filter_by(id=field_id, user_id=user_id).first()

    if not field:
        raise NotFoundError("Field not found")

    field_aliases = {
        "crop": "crop_type",
        "soilType": "soil_type",
        "irrigation": "irrigation_type",
        "plantingDate": "planting_date",
        "unit": "size_unit",
    }

    normalized_data = {}

    for key, value in data.items():
        normalized_key = field_aliases.get(key, key)

        if normalized_key not in normalized_data:
            normalized_data[normalized_key] = value

    if "name" in normalized_data:
        name = normalized_data["name"].strip()

        if not name:
            raise BadRequestError("Field name cannot be empty")

        field.name = name

    if "size" in normalized_data:
        try:
            size = float(normalized_data["size"])
        except (TypeError, ValueError):
            raise BadRequestError("Size must be a positive number")

        if size <= 0:
            raise BadRequestError("Size must be a positive number")

        field.size = size

    coordinates_changed = False

    if "coordinates" in normalized_data:
        latitude, longitude = _parse_coordinates(normalized_data["coordinates"])
        field.latitude = latitude
        field.longitude = longitude
        coordinates_changed = True

    if "latitude" in normalized_data:
        field.latitude = _coerce_coordinate(
            normalized_data["latitude"],
            "Latitude",
            -90,
            90
        )
        coordinates_changed = True

    if "longitude" in normalized_data:
        field.longitude = _coerce_coordinate(
            normalized_data["longitude"],
            "Longitude",
            -180,
            180
        )
        coordinates_changed = True

    if "location" in normalized_data:
        field.location = _resolve_location(
            normalized_data["location"],
            field.latitude,
            field.longitude
        )
    elif coordinates_changed:
        field.location = _resolve_location(
            None,
            field.latitude,
            field.longitude
        )

    if "country" in normalized_data:
        field.country = normalized_data["country"]

    if "crop_type" in normalized_data:
        crop_type = normalized_data["crop_type"].strip()

        if not crop_type:
            raise BadRequestError("Crop type cannot be empty")

        field.crop_type = crop_type

    if "soil_type" in normalized_data:
        field.soil_type = normalized_data["soil_type"]

    if "irrigation_type" in normalized_data:
        field.irrigation_type = normalized_data["irrigation_type"]

    if "notes" in normalized_data:
        field.notes = normalized_data["notes"]

    if "planting_date" in normalized_data:
        field.planting_date = _parse_planting_date(
            normalized_data["planting_date"]
        )

    if "size_unit" in normalized_data:
        size_unit = normalized_data["size_unit"]

        if size_unit not in ("acres", "hectares"):
            raise BadRequestError("Unit must be either acres or hectares")

        field.size_unit = size_unit

    db.session.commit()

    current_app.logger.info(
        "update field service completed",
        extra={
            "event": "field_service.update_completed",
            "field_id": field_id,
            "owner_user_id": user_id
        }
    )

    return field.to_dict()


def delete_field(field_id, user_id):
    current_app.logger.info(
        "delete field service started",
        extra={"event": "field_service.delete_started", "field_id": field_id, "owner_user_id": user_id}
    )

    field = Field.query.filter_by(id=field_id, user_id=user_id).first()
    if not field:
        raise NotFoundError("Field not found")

    related_delete_counts = _delete_related_field_records(field.id)

    db.session.delete(field)
    db.session.commit()

    current_app.logger.info(
        "delete field service completed",
        extra={
            "event": "field_service.delete_completed",
            "field_id": field_id,
            "owner_user_id": user_id,
            **related_delete_counts
        }
    )


def _delete_related_field_records(field_id):
    deleted_crop_analyses = CropAnalysis.query.filter_by(field_id=field_id).delete(
        synchronize_session=False
    )
    deleted_weather_data = WeatherData.query.filter_by(field_id=field_id).delete(
        synchronize_session=False
    )
    deleted_reports = Report.query.filter_by(field_id=field_id).delete(
        synchronize_session=False
    )

    return {
        "deleted_crop_analyses": deleted_crop_analyses,
        "deleted_weather_data": deleted_weather_data,
        "deleted_reports": deleted_reports
    }


def import_fields_from_csv(file_stream, user_id):
    current_app.logger.info(
        "csv field import service started",
        extra={"event": "field_service.csv_import_started", "owner_user_id": user_id}
    )

    try:
        text_stream = io.TextIOWrapper(file_stream, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text_stream)
        header_map = _build_csv_header_map(reader.fieldnames)
    except UnicodeDecodeError:
        raise BadRequestError("CSV file must be UTF-8 encoded")
    except csv.Error as error:
        raise BadRequestError(f"Invalid CSV file: {error}")

    if not header_map:
        raise BadRequestError("CSV file is empty or missing a header row")

    missing_columns = [column for column in REQUIRED_CSV_COLUMNS if column not in header_map]
    if missing_columns:
        raise BadRequestError(f"Missing required CSV columns: {', '.join(missing_columns)}")

    fields = []
    errors = []

    try:
        for row_number, row in enumerate(reader, start=2):
            if _is_blank_csv_row(row):
                continue

            data = _normalize_csv_row(row, header_map)
            row_errors = _validate_csv_field_data(data, row_number)
            if row_errors:
                errors.extend(row_errors)
                continue

            try:
                planting_date = _parse_planting_date(data.get("planting_date"))
            except BadRequestError as error:
                errors.append(f"Row {row_number}: {error.message}")
                continue

            fields.append(_create_field_model(data, user_id, planting_date))
    except UnicodeDecodeError:
        raise BadRequestError("CSV file must be UTF-8 encoded")
    except csv.Error as error:
        raise BadRequestError(f"Invalid CSV file: {error}")

    if errors:
        raise BadRequestError("CSV import failed", details=errors)

    if not fields:
        raise BadRequestError("CSV file does not contain any field rows")

    db.session.add_all(fields)
    db.session.commit()

    return [field.to_dict() for field in fields]


def _parse_planting_date(value):
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise BadRequestError("Invalid date format. Use YYYY-MM-DD")


def _create_field_model(data, user_id, planting_date):
    latitude = _coerce_coordinate(data.get("latitude"), "Latitude", -90, 90)
    longitude = _coerce_coordinate(data.get("longitude"), "Longitude", -180, 180)
    coordinates = data.get("coordinates")

    if coordinates and (latitude is None or longitude is None):
        latitude, longitude = _parse_coordinates(coordinates)

    location = _resolve_location(data.get("location"), latitude, longitude)

    return Field(
        name=data["name"].strip(),
        size=data["size"],
        size_unit=data.get("size_unit") or data.get("unit") or "hectares",
        location=location,
        country=data.get("country"),
        latitude=latitude,
        longitude=longitude,
        crop_type=data["crop_type"].strip(),
        soil_type=data.get("soil_type"),
        irrigation_type=data.get("irrigation_type"),
        notes=data.get("notes"),
        planting_date=planting_date,
        user_id=user_id
    )


def _build_csv_header_map(fieldnames):
    if not fieldnames:
        return {}

    header_map = {}
    for fieldname in fieldnames:
        if fieldname is None:
            continue
        normalized_name = fieldname.strip().lower()
        if normalized_name and normalized_name not in header_map:
            header_map[normalized_name] = fieldname

    return header_map


def _is_blank_csv_row(row):
    return not any((value or "").strip() for key, value in row.items() if key)


def _normalize_csv_row(row, header_map):
    data = {}
    for column in CSV_COLUMNS:
        header = header_map.get(column)
        raw_value = row.get(header, "") if header else ""
        value = raw_value.strip() if raw_value else ""
        data[column] = value

    data["size"] = _parse_csv_size(data["size"])

    for column in OPTIONAL_CSV_COLUMNS:
        if data[column] == "":
            data[column] = None

    return data


def _parse_csv_size(value):
    if value == "":
        return value

    try:
        return float(value)
    except ValueError:
        return value


def _validate_csv_field_data(data, row_number):
    errors = []

    for column in REQUIRED_CSV_COLUMNS:
        if data[column] == "":
            errors.append(f"Row {row_number}: {column} is required")

    if errors:
        return errors

    valid, error = validate_field_input(data)
    if not valid:
        errors.append(f"Row {row_number}: {error}")

    return errors


def _parse_coordinates(value):
    if not value:
        return None, None

    if isinstance(value, str):
        try:
            lat_raw, lon_raw = value.split(",", 1)
            return (
                _coerce_coordinate(lat_raw, "Latitude", -90, 90),
                _coerce_coordinate(lon_raw, "Longitude", -180, 180)
            )
        except ValueError:
            raise BadRequestError("Invalid coordinates format. Use 'lat, lon'")

    if isinstance(value, dict):
        lat_raw = value.get("lat", value.get("latitude"))
        lon_raw = value.get("lng", value.get("longitude"))
        if lat_raw in (None, "") or lon_raw in (None, ""):
            raise BadRequestError("Coordinates object must include lat/lng values")
        return (
            _coerce_coordinate(lat_raw, "Latitude", -90, 90),
            _coerce_coordinate(lon_raw, "Longitude", -180, 180)
        )

    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (
            _coerce_coordinate(value[0], "Latitude", -90, 90),
            _coerce_coordinate(value[1], "Longitude", -180, 180)
        )

    raise BadRequestError("Invalid coordinates format. Use 'lat, lon'")


def _coerce_coordinate(value, label, min_value, max_value):
    if value in (None, ""):
        return None

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        raise BadRequestError(f"{label} must be a valid number")

    if not (min_value <= numeric_value <= max_value):
        raise BadRequestError(f"{label} must be between {min_value} and {max_value}")

    return numeric_value


def _resolve_location(location_value, latitude, longitude):
    if isinstance(location_value, str) and location_value.strip():
        return location_value.strip()

    if latitude is not None and longitude is not None:
        resolved = reverse_geocode(latitude, longitude)
        if resolved and resolved.strip():
            return resolved.strip()
        return f"{round(latitude, 4)}, {round(longitude, 4)}"

    raise BadRequestError("Provide either location or coordinates (latitude/longitude)")


def _extract_location_name(address):
    if not isinstance(address, dict):
        return None

    locality_keys = (
        "city",
        "town",
        "village",
        "municipality",
        "county",
        "state_district",
        "state",
        "country",
    )

    for key in locality_keys:
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None
