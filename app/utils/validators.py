import validators


def validate_register_input(data):
    required_fields = ["email", "password"]
    missing = [field for field in required_fields if field not in data]
    if "fullname" not in data and "fullName" not in data:
        missing.append("fullname")

    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    email = data.get("email", "").strip()
    password = data.get("password", "")
    full_name = data.get("fullname") or data.get("fullName") or ""

    if not validators.email(email):
        return False, "Invalid email address"

    if len(password) < 6:
        return False, "Password must be at least 6 characters long"

    if len(full_name.strip()) < 3:
        return False, "Name must be more than 3 characters long"

    return True, None


def validate_login_input(data):
    required_fields = ["email", "password"]
    missing = [field for field in required_fields if field not in data]

    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    return True, None


def _coerce_size(value):
    """Прифаќа float, int или string ('15', '15.5'). Враќа float или None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def validate_field_input(data):
    """Прифаќа двата облика на клучеви:
    - crop_type (canonical) или crop (frontend alias)
    - soil_type / soilType
    - irrigation_type / irrigation
    - planting_date / plantingDate
    Размислувај дека validate-от исто така *нормализира* — додава canonical клуч
    ако постои само alias-от."""

    if "crop_type" not in data and "crop" in data:
        data["crop_type"] = data["crop"]
    if "soil_type" not in data and "soilType" in data:
        data["soil_type"] = data["soilType"]
    if "irrigation_type" not in data and "irrigation" in data:
        data["irrigation_type"] = data["irrigation"]
    if "planting_date" not in data and "plantingDate" in data:
        data["planting_date"] = data["plantingDate"]
    if "size_unit" not in data and "unit" in data:
        data["size_unit"] = data["unit"]

    required_fields = ["name", "size", "location", "crop_type"]
    missing = [field for field in required_fields if field not in data or data.get(field) in (None, "")]

    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    size_value = _coerce_size(data["size"])
    if size_value is None or size_value <= 0:
        return False, "Size must be a positive number"

    data["size"] = size_value

    if not isinstance(data["name"], str) or len(data["name"].strip()) < 2:
        return False, "Field name must be at least 2 characters"

    if not isinstance(data["location"], str) or len(data["location"].strip()) < 2:
        return False, "Location must be at least 2 characters"

    if not isinstance(data["crop_type"], str) or len(data["crop_type"].strip()) < 2:
        return False, "Crop type must be at least 2 characters"

    unit = data.get("size_unit")
    if unit and unit not in ("acres", "hectares"):
        return False, "Unit must be either acres or hectares"

    return True, None
