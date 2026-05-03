from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.errors import BadRequestError
from app.services.field_service import (
    get_all_fields,
    get_field_by_id,
    create_field,
    update_field,
    delete_field,
    import_fields_from_csv
)
from app.utils.validators import validate_field_input

fields_bp = Blueprint('fields', __name__)


@fields_bp.route('/', methods=['GET'])
@jwt_required()
def get_fields():
    """
    Врати ги сите ниви на корисникот
    ---
    tags:
      - Fields
    security:
      - BearerAuth: []
    responses:
      200:
        description: Листа на ниви
        schema:
          type: object
          properties:
            success:
              type: boolean
            fields:
              type: array
              items:
                type: object
      401:
        description: Неавторизиран пристап
    """
    user_id = get_jwt_identity()
    current_app.logger.info(
        "get fields request received",
        extra={"event": "fields.list_started", "owner_user_id": user_id}
    )

    fields = get_all_fields(user_id)
    return jsonify({"success": True, "fields": fields}), 200


@fields_bp.route('/<int:field_id>', methods=['GET'])
@jwt_required()
def get_field(field_id):
    """
    Врати една нива по ID
    ---
    tags:
      - Fields
    security:
      - BearerAuth: []
    parameters:
      - name: field_id
        in: path
        type: integer
        required: true
        description: ID на нивата
    responses:
      200:
        description: Нивата е пронајдена
      404:
        description: Нивата не е пронајдена
      401:
        description: Неавторизиран пристап
    """
    user_id = get_jwt_identity()
    current_app.logger.info(
        "get field request received",
        extra={"event": "fields.get_started", "field_id": field_id, "owner_user_id": user_id}
    )

    field = get_field_by_id(field_id, user_id)
    return jsonify({"success": True, "field": field}), 200


@fields_bp.route('/', methods=['POST'])
@jwt_required()
def add_field():
    """
    Додај нова нива
    ---
    tags:
      - Fields
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - name
            - size
            - location
            - crop_type
          properties:
            name:
              type: string
              example: Нива 1
            size:
              type: number
              example: 2.5
            location:
              type: string
              example: Скопје
            crop_type:
              type: string
              example: Пченица
            soil_type:
              type: string
              example: Глинеста
            irrigation_type:
              type: string
              example: Капка по капка
            notes:
              type: string
              example: Белешки за нивата
            planting_date:
              type: string
              example: "2026-04-01"
            latitude:
              type: number
              format: float
              example: 41.9981
              description: "Географска ширина (-90 до 90)."
            longitude:
              type: number
              format: float
              example: 21.4254
              description: "Географска должина (-180 до 180)."
    responses:
      201:
        description: Нивата е успешно креирана
      400:
        description: Невалидни податоци
      401:
        description: Неавторизиран пристап
    """
    user_id = get_jwt_identity()
    data = request.get_json(silent=True)
    current_app.logger.info(
        "create field request received",
        extra={
            "event": "fields.create_started",
            "owner_user_id": user_id,
            "body_fields": list(data.keys()) if isinstance(data, dict) else [],
            "has_notes": bool(data.get("notes")) if isinstance(data, dict) else False,
            "has_planting_date": bool(data.get("planting_date")) if isinstance(data, dict) else False
        }
    )

    if not data:
        raise BadRequestError("Invalid JSON body")

    valid, error = validate_field_input(data)
    if not valid:
        raise BadRequestError(error)

    field = create_field(data, user_id)

    current_app.logger.info(
        "field created",
        extra={"event": "fields.created", "field_id": field["id"], "owner_user_id": user_id}
    )

    return jsonify({"success": True, "message": "Field created successfully", "field": field}), 201


@fields_bp.route('/upload', methods=['POST'])
@jwt_required()
def upload_fields_csv():
    """
    Прикачи CSV фајл со ниви
    ---
    tags:
      - Fields
    security:
      - BearerAuth: []
    consumes:
      - multipart/form-data
    parameters:
      - in: formData
        name: file
        type: file
        required: true
        description: CSV фајл со колони name, size, location, crop_type, soil_type, irrigation_type, notes, planting_date
    responses:
      201:
        description: Нивите се успешно импортирани
      400:
        description: Невалиден CSV фајл или податоци
      401:
        description: Неавторизиран пристап
    """
    user_id = get_jwt_identity()
    current_app.logger.info(
        "csv field import request received",
        extra={
            "event": "fields.csv_import_request_started",
            "owner_user_id": user_id,
            "file_present": "file" in request.files,
            "content_length": request.content_length
        }
    )

    if 'file' not in request.files:
        raise BadRequestError("CSV file is required")

    csv_file = request.files['file']
    if not csv_file or not csv_file.filename:
        raise BadRequestError("CSV file is required")

    if not csv_file.filename.lower().endswith('.csv'):
        raise BadRequestError("Only CSV files are allowed")

    current_app.logger.info(
        "csv field import started",
        extra={"event": "fields.csv_import_started", "owner_user_id": user_id}
    )

    fields = import_fields_from_csv(csv_file.stream, user_id)

    current_app.logger.info(
        "csv field import completed",
        extra={
            "event": "fields.csv_import_completed",
            "owner_user_id": user_id,
            "imported_count": len(fields)
        }
    )

    return jsonify({
        "success": True,
        "message": "Fields imported successfully",
        "imported_count": len(fields),
        "fields": fields
    }), 201


@fields_bp.route('/<int:field_id>', methods=['PUT'])
@jwt_required()
def edit_field(field_id):
    """
    Уреди постоечка нива
    ---
    tags:
      - Fields
    security:
      - BearerAuth: []
    parameters:
      - name: field_id
        in: path
        type: integer
        required: true
        description: ID на нивата
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
              example: Нива 1 - Уредена
            size:
              type: number
              example: 3.0
            location:
              type: string
              example: Битола
            crop_type:
              type: string
              example: Домати
            soil_type:
              type: string
              example: Песочна
            irrigation_type:
              type: string
              example: Попрскување
            notes:
              type: string
              example: Ажурирани белешки
            planting_date:
              type: string
              example: "2026-05-01"
    responses:
      200:
        description: Нивата е успешно уредена
      400:
        description: Невалидни податоци
      404:
        description: Нивата не е пронајдена
      401:
        description: Неавторизиран пристап
    """
    user_id = get_jwt_identity()
    data = request.get_json(silent=True)
    current_app.logger.info(
        "update field request received",
        extra={
            "event": "fields.update_started",
            "field_id": field_id,
            "owner_user_id": user_id,
            "body_fields": list(data.keys()) if isinstance(data, dict) else []
        }
    )

    if not data:
        raise BadRequestError("Invalid JSON body")

    field = update_field(field_id, data, user_id)

    current_app.logger.info(
        "field updated",
        extra={"event": "fields.updated", "field_id": field["id"], "owner_user_id": user_id}
    )

    return jsonify({"success": True, "message": "Field updated successfully", "field": field}), 200


@fields_bp.route('/<int:field_id>', methods=['DELETE'])
@jwt_required()
def remove_field(field_id):
    """
    Избриши нива
    ---
    tags:
      - Fields
    security:
      - BearerAuth: []
    parameters:
      - name: field_id
        in: path
        type: integer
        required: true
        description: ID на нивата
    responses:
      200:
        description: Нивата е успешно избришана
      404:
        description: Нивата не е пронајдена
      401:
        description: Неавторизиран пристап
    """
    user_id = get_jwt_identity()
    current_app.logger.info(
        "delete field request received",
        extra={"event": "fields.delete_started", "field_id": field_id, "owner_user_id": user_id}
    )

    delete_field(field_id, user_id)

    current_app.logger.info(
        "field deleted",
        extra={"event": "fields.deleted", "field_id": field_id, "owner_user_id": user_id}
    )

    return jsonify({"success": True, "message": "Field deleted successfully"}), 200
