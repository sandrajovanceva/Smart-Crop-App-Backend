from flask import Blueprint, jsonify

advisor_bp = Blueprint('advisor', __name__)

@advisor_bp.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200