import csv
import io
import textwrap
from datetime import datetime, timedelta

from flask import Blueprint, current_app, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app import db
from app.errors import BadRequestError, NotFoundError
from app.models.Field import Field
from app.models.Report import Report
from app.utils.report_generators import generate_report_payload

reports_bp = Blueprint('reports', __name__)

VALID_REPORT_TYPES = {
    "Crop Analysis",
    "Disease Risk",
    "Fertilizer",
    "Weather Analysis",
    "Irrigation",
}


def _resolve_report_request(data, user_id):
    field_id = data.get("field_id")
    report_type = data.get("type") or data.get("report_type")

    if not field_id or not report_type:
        raise BadRequestError("Missing required fields: field_id, report_type")

    if report_type not in VALID_REPORT_TYPES:
        raise BadRequestError(
            f"Invalid report_type. Must be one of: {', '.join(sorted(VALID_REPORT_TYPES))}"
        )

    field = Field.query.filter_by(id=field_id, user_id=user_id).first()

    if not field:
        raise NotFoundError("Field not found")

    return field, report_type


@reports_bp.route('/', methods=['GET'])
@jwt_required()
def list_reports():
    """
    Врати ги сите reports на корисникот
    ---
    tags:
      - Reports
    security:
      - BearerAuth: []
    parameters:
      - name: field_id
        in: query
        type: integer
        required: false
        description: Филтрирај по нива
      - name: type
        in: query
        type: string
        required: false
        description: 'Crop Analysis | Disease Risk | Fertilizer | Weather Analysis | Irrigation'
    responses:
      200:
        description: Листа на reports
    """
    user_id = get_jwt_identity()
    field_id = request.args.get('field_id', type=int)
    report_type = request.args.get('type', type=str)

    current_app.logger.info(
        "list reports request received",
        extra={
            "event": "reports.list_started",
            "owner_user_id": user_id,
            "field_id": field_id,
            "report_type": report_type
        }
    )

    query = Report.query.filter_by(user_id=user_id)
    if field_id:
        query = query.filter_by(field_id=field_id)
    if report_type:
        query = query.filter_by(report_type=report_type)

    reports = query.order_by(Report.created_at.desc()).all()

    return jsonify({
        "success": True,
        "reports": [r.to_dict() for r in reports],
        "stats": _compute_stats(user_id, reports)
    }), 200


def _compute_stats(user_id, reports):
    """Брои реални метрики за stat картичките во ReportsPage."""
    one_month_ago = datetime.utcnow() - timedelta(days=30)
    one_week_ago = datetime.utcnow() - timedelta(days=7)

    total = len(reports)

    new_this_month = sum(
        1 for report in reports
        if report.created_at and report.created_at >= one_month_ago
    )

    field_ids = {
        report.field_id for report in reports
        if report.field_id
    }

    pdf_downloads_this_week = sum(
        report.pdf_download_count or 0
        for report in reports
        if report.last_downloaded_at
        and report.last_downloaded_at >= one_week_ago
    )

    ai_recommendations = sum(
        1 for report in reports
        if report.report_type in {
            "Crop Analysis",
            "Disease Risk",
            "Fertilizer",
            "Weather Analysis",
            "Irrigation",
        }
    )

    return {
        "total_reports": total,
        "new_this_month": new_this_month,
        "fields_analyzed": len(field_ids),
        "ai_recommendations": ai_recommendations,
        "pdf_downloads_this_week": pdf_downloads_this_week,

        "cards": [
            {
                "label": "Total Reports",
                "value": str(total),
                "change": f"+{new_this_month} this month",
                "iconName": "FileText"
            },
            {
                "label": "PDF Downloads",
                "value": str(pdf_downloads_this_week),
                "change": "This week",
                "iconName": "Download"
            },
            {
                "label": "Fields Analyzed",
                "value": str(len(field_ids)),
                "change": "Active fields",
                "iconName": "BarChart3"
            },
            {
                "label": "AI Recommendations",
                "value": str(ai_recommendations),
                "change": "Generated insights",
                "iconName": "Brain"
            }
        ]
    }


def _resolve_report_summary(report):
    if report.summary and report.summary.strip():
        return report.summary.strip()

    payload = report.payload if isinstance(report.payload, dict) else {}
    payload_summary = payload.get("summary")
    if isinstance(payload_summary, str) and payload_summary.strip():
        return payload_summary.strip()

    return "No summary"


@reports_bp.route('/<int:report_id>', methods=['GET'])
@jwt_required()
def get_report(report_id):
    """
    Врати еден report со целосен payload
    ---
    tags:
      - Reports
    security:
      - BearerAuth: []
    parameters:
      - name: report_id
        in: path
        type: integer
        required: true
        description: ID на извештајот
        example: 1
    responses:
      200:
        description: Успешно вратен report
      404:
        description: Report not found
    """
    user_id = get_jwt_identity()
    report = Report.query.filter_by(id=report_id, user_id=user_id).first()
    if not report:
        raise NotFoundError("Report not found")
    return jsonify({"success": True, "report": report.to_dict(include_payload=True)}), 200


@reports_bp.route('/', methods=['POST'])
@jwt_required()
def create_report():
    """
    Креирај нов report
    ---
    tags:
      - Reports
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - field_id
            - report_type
          properties:
            field_id:
              type: integer
              example: 1
              description: ID на нивата за која се креира report.
            report_type:
              type: string
              example: 'Disease Risk'
              description: 'Crop Analysis | Disease Risk | Fertilizer | Weather Analysis | Irrigation'
            title:
              type: string
              example: 'Нива 1 - Disease Risk'
              description: Optional. Ако не е пратено, backend сам генерира title.
            summary:
              type: string
              example: 'Краток опис на анализата'
              description: Optional summary.
            payload:
              type: object
              description: Optional содржина на report-от, на пример AI response payload.
          example:
            field_id: 1
            report_type: 'Disease Risk'
    responses:
      201:
        description: Креиран report
      400:
        description: Невалиден request
      404:
        description: Field not found
    """
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    field, report_type = _resolve_report_request(data, user_id)

    title = data.get('title') or f"{field.name} - {report_type}"

    report = Report(
        title=title,
        report_type=report_type,
        summary=data.get('summary'),
        payload=data.get('payload') or {},
        status='Completed',
        file_size=data.get('file_size'),
        field_id=field.id,
        user_id=user_id,
    )

    db.session.add(report)
    db.session.commit()

    current_app.logger.info(
        "report created",
        extra={"event": "reports.created", "report_id": report.id, "owner_user_id": user_id}
    )

    return jsonify({"success": True, "report": report.to_dict()}), 201


@reports_bp.route('/<int:report_id>', methods=['DELETE'])
@jwt_required()
def delete_report(report_id):
    """
    Избриши report
    ---
    tags:
      - Reports
    security:
      - BearerAuth: []
    parameters:
      - name: report_id
        in: path
        type: integer
        required: true
        description: ID на извештајот
        example: 1
    responses:
      200:
        description: Report deleted
      404:
        description: Report not found
    """
    user_id = get_jwt_identity()
    report = Report.query.filter_by(id=report_id, user_id=user_id).first()
    if not report:
        raise NotFoundError("Report not found")

    db.session.delete(report)
    db.session.commit()
    return jsonify({"success": True, "message": "Report deleted"}), 200


@reports_bp.route('/generate', methods=['POST'])
@jwt_required()
def generate_report():
    """
    Генерирај report за нива
    ---
    tags:
      - Reports
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - field_id
            - report_type
          properties:
            field_id:
              type: integer
              example: 1
              description: ID на нивата.
            report_type:
              type: string
              example: 'Disease Risk'
              description: 'Crop Analysis | Disease Risk | Fertilizer | Weather Analysis | Irrigation'
            growth_stage:
              type: string
              example: 'Vegetative'
              description: Optional, се користи за Fertilizer reports.
          example:
            field_id: 1
            report_type: 'Disease Risk'
    responses:
      201:
        description: Report generated successfully
      400:
        description: Невалиден request
      404:
        description: Field not found
    """
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    field, report_type = _resolve_report_request(data, user_id)

    payload = generate_report_payload(
        field=field,
        report_type=report_type,
        data=data
    )

    title = data.get("title") or f"{field.name} - {report_type}"
    summary = data.get("summary") or payload.get("summary")

    report = Report(
        title=title,
        report_type=report_type,
        summary=summary,
        payload=payload,
        status="Completed",
        file_size=data.get("file_size"),
        field_id=field.id,
        user_id=user_id,
    )

    db.session.add(report)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Report generated successfully",
        "report": report.to_dict(include_payload=True)
    }), 201


@reports_bp.route('/export/csv', methods=['GET'])
@jwt_required()
def export_reports_csv():
    user_id = get_jwt_identity()

    reports = Report.query.filter_by(user_id=user_id).order_by(Report.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["Name", "Field", "Type", "Date", "Size", "Status"])

    for report in reports:
        row = report.to_dict()
        writer.writerow([
            row["name"],
            row["field"],
            row["type"],
            row["date"],
            row["size"],
            row["status"],
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=reports.csv"
        }
    )


@reports_bp.route('/<int:report_id>/download/pdf', methods=['GET'])
@jwt_required()
def download_report_pdf(report_id):
    """
    Преземи report како PDF
    ---
    tags:
      - Reports
    security:
      - BearerAuth: []
    produces:
      - application/pdf
    parameters:
      - name: report_id
        in: path
        type: integer
        required: true
        description: ID на извештајот
        example: 1
    responses:
      200:
        description: PDF file
        schema:
          type: file
      404:
        description: Report not found
    """
    user_id = get_jwt_identity()

    report = Report.query.filter_by(id=report_id, user_id=user_id).first()
    if not report:
        raise NotFoundError("Report not found")

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    pdf.drawString(50, 800, report.title)
    pdf.drawString(50, 775, f"Type: {report.report_type}")
    pdf.drawString(50, 750, f"Field: {report.field.name if report.field else '—'}")
    pdf.drawString(50, 725, f"Status: {report.status}")

    summary_text = _resolve_report_summary(report)
    summary_lines = textwrap.wrap(f"Summary: {summary_text}", width=90)
    y = 700
    for line in summary_lines:
        pdf.drawString(50, y, line)
        y -= 15

    pdf.showPage()
    pdf.save()

    report.pdf_download_count = (report.pdf_download_count or 0) + 1
    report.last_downloaded_at = datetime.utcnow()
    db.session.commit()

    buffer.seek(0)

    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=report-{report.id}.pdf"
        }
    )
