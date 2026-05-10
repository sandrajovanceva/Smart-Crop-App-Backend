from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    get_jwt,
    get_jwt_identity,
    jwt_required
)

from app import db, bcrypt
from app.errors import BadRequestError, ConflictError, NotFoundError, UnauthorizedError
from app.models.User import User
from app.models.TokenBlocklist import TokenBlocklist
from app.utils.validators import validate_register_input, validate_login_input

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Регистрирај нов корисник
    ---
    tags:
      - Auth
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - email
            - password
          properties:
            email:
              type: string
              example: test@gmail.com
            password:
              type: string
              example: pass1234!
            fullname:
              type: string
              description: Може да се испрати и како `fullName` (camelCase)
              example: Test User
    responses:
      201:
        description: Корисникот е успешно регистриран
      400:
        description: Невалидни податоци
      409:
        description: Емаилот веќе постои
    """
    data = request.get_json(silent=True)
    current_app.logger.info(
        "register request received",
        extra={
            "event": "auth.register_started",
            "body_fields": list(data.keys()) if isinstance(data, dict) else []
        }
    )

    if not data:
        raise BadRequestError("Invalid JSON body")

    valid, error = validate_register_input(data)
    if not valid:
        raise BadRequestError(error)

    email = data["email"].strip()
    full_name = (data.get("fullname") or data.get("fullName") or "").strip()

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        raise ConflictError("Email already exists")

    password_hash = bcrypt.generate_password_hash(data["password"]).decode("utf-8")
    user = User(email=email, password_hash=password_hash, full_name=full_name)

    db.session.add(user)
    db.session.commit()

    current_app.logger.info(
        "user registered",
        extra={"event": "auth.user_registered", "registered_user_id": user.id}
    )

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={"email": user.email}
    )

    return jsonify({
        "success": True,
        "message": "User registered successfully",
        "user": user.to_dict(),
        "access_token": access_token,
        "token": access_token
    }), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    """
    Најава на корисник
    ---
    tags:
      - Auth
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - email
            - password
          properties:
            email:
              type: string
              example: test@gmail.com
            password:
              type: string
              example: pass1234!
    responses:
      200:
        description: Успешна најава, враќа access_token
      400:
        description: Невалидни податоци
      401:
        description: Погрешен емаил или лозинка
    """
    data = request.get_json(silent=True)
    current_app.logger.info(
        "login request received",
        extra={
            "event": "auth.login_started",
            "body_fields": list(data.keys()) if isinstance(data, dict) else []
        }
    )

    if not data:
        raise BadRequestError("Invalid JSON body")

    valid, error = validate_login_input(data)
    if not valid:
        raise BadRequestError(error)

    email = data["email"].strip()
    password = data["password"]

    user = User.query.filter_by(email=email).first()

    if not user or not bcrypt.check_password_hash(user.password_hash, password):
        current_app.logger.warning("login failed", extra={"event": "auth.login_failed"})
        raise UnauthorizedError("Invalid email or password")

    current_app.logger.info(
        "login successful",
        extra={"event": "auth.login_success", "authenticated_user_id": user.id}
    )

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={"email": user.email}
    )

    return jsonify({
        "success": True,
        "message": "Login successful",
        "access_token": access_token,
        "token": access_token,
        "user": user.to_dict()
    }), 200


@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    """
    Одјава на корисник
    ---
    tags:
      - Auth
    security:
      - BearerAuth: []
    responses:
      200:
        description: Успешна одјава
      401:
        description: Неавторизиран пристап
    """
    user_id = get_jwt_identity()
    current_app.logger.info(
        "logout request received",
        extra={"event": "auth.logout_started", "authenticated_user_id": user_id}
    )

    jwt_data = get_jwt()
    jti = jwt_data["jti"]

    blocked_token = TokenBlocklist(jti=jti)
    db.session.add(blocked_token)
    db.session.commit()

    current_app.logger.info(
        "logout successful",
        extra={"event": "auth.logout_success", "authenticated_user_id": user_id}
    )

    return jsonify({
        "success": True,
        "message": "Logout successful. Token has been invalidated"
    }), 200


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    """
    Врати го тековниот корисник
    ---
    tags:
      - Auth
    security:
      - BearerAuth: []
    responses:
      200:
        description: Информации за корисникот
      404:
        description: Корисникот не е пронајден
      401:
        description: Неавторизиран пристап
    """
    user_id = get_jwt_identity()
    current_app.logger.info(
        "me request received",
        extra={"event": "auth.me_started", "authenticated_user_id": user_id}
    )

    user = User.query.filter_by(id=user_id).first()

    if not user:
        raise NotFoundError("User not found")

    return jsonify({
        "success": True,
        "user": user.to_dict()
    }), 200
