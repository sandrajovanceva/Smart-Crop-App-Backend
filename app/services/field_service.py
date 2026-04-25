import csv
import io
from datetime import datetime

from app import db
from app.models.Field import Field
from app.utils.validators import validate_field_input


REQUIRED_CSV_COLUMNS = ["name", "size", "location", "crop_type"]
OPTIONAL_CSV_COLUMNS = ["soil_type", "irrigation_type", "notes", "planting_date"]
CSV_COLUMNS = REQUIRED_CSV_COLUMNS + OPTIONAL_CSV_COLUMNS


def get_all_fields(user_id):
    fields = Field.query.filter_by(user_id=user_id).all()
    return [f.to_dict() for f in fields]


def get_field_by_id(field_id, user_id):
    field = Field.query.filter_by(id=field_id, user_id=user_id).first()
    if not field:
        return None, "Field not found"
    return field.to_dict(), None


def create_field(data, user_id):
    planting_date, error = _parse_planting_date(data.get("planting_date"))
    if error:
        return None, error

    field = _create_field_model(data, user_id, planting_date)

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

def import_fields_from_csv(file_stream, user_id):
    try:
        text_stream = io.TextIOWrapper(file_stream, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text_stream)
        header_map = _build_csv_header_map(reader.fieldnames)
    except UnicodeDecodeError:
        return None, ["CSV file must be UTF-8 encoded"]
    except csv.Error as error:
        return None, [f"Invalid CSV file: {error}"]

    if not header_map:
        return None, ["CSV file is empty or missing a header row"]

    missing_columns = [column for column in REQUIRED_CSV_COLUMNS if column not in header_map]
    if missing_columns:
        return None, [f"Missing required CSV columns: {', '.join(missing_columns)}"]

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

            planting_date, error = _parse_planting_date(data.get("planting_date"))
            if error:
                errors.append(f"Row {row_number}: {error}")
                continue

            fields.append(_create_field_model(data, user_id, planting_date))
    except UnicodeDecodeError:
        return None, ["CSV file must be UTF-8 encoded"]
    except csv.Error as error:
        return None, [f"Invalid CSV file: {error}"]

    if errors:
        return None, errors

    if not fields:
        return None, ["CSV file does not contain any field rows"]

    db.session.add_all(fields)
    db.session.commit()

    return [field.to_dict() for field in fields], None


def _parse_planting_date(value):
    if not value:
        return None, None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date(), None
    except ValueError:
        return None, "Invalid date format. Use YYYY-MM-DD"


def _create_field_model(data, user_id, planting_date):
    return Field(
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
