import validators

def validate_register_input(data):
    required_fields = ["email", "password", "fullname"]
    missing = [field for field in required_fields if field not in data]

    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    email = data.get("email", "").strip()
    password = data.get("password", "")
    fullName = data.get("fullname", "")

    if not validators.email(email):
        return False, "Invalid email address"
    
    if len(password) < 6:
        return False, "Password must be at least 6 characters long"

    if len(fullName) < 3:
        return False, "Name must be more than 3 characters long"
    
    return True, None

def validate_login_input(data):
    required_fields = ["email", "password"]
    missing = [field for field in required_fields if field not in data]

    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"
    
    return True, None

def validate_field_input(data):
    required_fields = ["name", "size", "location", "crop_type"]
    missing = [field for field in required_fields if field not in data]

    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    if not isinstance(data["size"], (int, float)) or data["size"] <= 0:
        return False, "Size must be a positive number"

    if len(data["name"].strip()) < 2:
        return False, "Field name must be at least 2 characters"

    if len(data["location"].strip()) < 2:
        return False, "Location must be at least 2 characters"

    return True, None

