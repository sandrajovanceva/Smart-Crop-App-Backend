from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.services.field_service import (
    get_all_fields,
    get_field_by_id,
    create_field,
    update_field,
    delete_field
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
    field, error = get_field_by_id(field_id, user_id)
    if error:
        return jsonify({"success": False, "error": error}), 404
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
              example: Капково
            notes:
              type: string
              example: Белешки за нивата
            planting_date:
              type: string
              example: "2026-04-01"
    responses:
      201:
        description: Нивата е успешно креирана
      400:
        description: Невалидни податоци
      401:
        description: Неавторизиран пристап
    """
    user_id = get_jwt_identity()
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "error": "Invalid JSON body"}), 400

    valid, error = validate_field_input(data)
    if not valid:
        return jsonify({"success": False, "error": error}), 400

    field, error = create_field(data, user_id)
    if error:
        return jsonify({"success": False, "error": error}), 400

    return jsonify({"success": True, "message": "Field created successfully", "field": field}), 201


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
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "error": "Invalid JSON body"}), 400

    field, error = update_field(field_id, data, user_id)
    if error:
        return jsonify({"success": False, "error": error}), 404 if "not found" in error else 400

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
    success, error = delete_field(field_id, user_id)
    if not success:
        return jsonify({"success": False, "error": error}), 404

    return jsonify({"success": True, "message": "Field deleted successfully"}), 200