import csv
import io
import json
import textwrap
from datetime import datetime

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
    }), 200


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

    payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    file_size = round(payload_bytes / (1024 * 1024), 3)

    report = Report(
        title=title,
        report_type=report_type,
        summary=summary,
        payload=payload,
        status="Completed",
        file_size=file_size,
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

    writer.writerow(["Name", "Field", "Type", "Date", "Size", "Summary"])

    for report in reports:
        row = report.to_dict()
        writer.writerow([
            row["name"],
            row["field"],
            row["type"],
            row["date"],
            row["size"],
            row["summary"] or "",
        ])

    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=reports.csv"
        }
    )

_PDF_LEFT = 50
_PDF_RIGHT = 545
_PDF_BOTTOM = 65
_PDF_TOP = 800
_PDF_LINE = 16


def _pdf_ensure_space(pdf, y, needed=None):
    if needed is None:
        needed = _PDF_LINE
    if y - needed < _PDF_BOTTOM:
        pdf.showPage()
        pdf.setFont("Helvetica", 10)
        return _PDF_TOP
    return y


def _pdf_section_header(pdf, y, title):
    y = _pdf_ensure_space(pdf, y, 40)
    y -= 8
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(_PDF_LEFT, y, title)
    y -= 5
    pdf.setLineWidth(0.5)
    pdf.line(_PDF_LEFT, y, _PDF_RIGHT, y)
    y -= _PDF_LINE
    pdf.setFont("Helvetica", 10)
    return y


def _pdf_kv(pdf, y, label, value):
    val_str = str(value) if value is not None else "—"
    y = _pdf_ensure_space(pdf, y)
    pdf.setFont("Helvetica-Bold", 10)
    label_text = f"{label}: "
    label_w = pdf.stringWidth(label_text, "Helvetica-Bold", 10)
    pdf.drawString(_PDF_LEFT + 10, y, label_text)
    pdf.setFont("Helvetica", 10)
    avail_w = _PDF_RIGHT - _PDF_LEFT - 10 - label_w
    val_lines = textwrap.wrap(val_str, width=max(20, int(avail_w / 5.5))) or [val_str]
    pdf.drawString(_PDF_LEFT + 10 + label_w, y, val_lines[0])
    y -= _PDF_LINE
    for extra in val_lines[1:]:
        y = _pdf_ensure_space(pdf, y)
        pdf.drawString(_PDF_LEFT + 10 + label_w, y, extra)
        y -= _PDF_LINE
    return y


def _pdf_bullet(pdf, y, text):
    lines = textwrap.wrap(text, width=78) or [text]
    for i, line in enumerate(lines):
        y = _pdf_ensure_space(pdf, y)
        pdf.setFont("Helvetica", 10)
        prefix = "•  " if i == 0 else "    "
        pdf.drawString(_PDF_LEFT + 15, y, prefix + line)
        y -= _PDF_LINE
    return y


def _pdf_body_crop_analysis(pdf, payload, y):
    health_data = payload.get("healthData") or payload.get("health_data") or []
    if health_data:
        y = _pdf_section_header(pdf, y, "Crop Health")
        for item in health_data:
            if isinstance(item, dict):
                y = _pdf_kv(pdf, y, item.get("name", "Health"), f"{item.get('value', '—')}/100")

    conditions = payload.get("conditions") or []
    if conditions:
        y = _pdf_section_header(pdf, y, "Current Conditions")
        for c in conditions:
            if isinstance(c, dict):
                y = _pdf_kv(pdf, y, c.get("label") or c.get("name", ""), c.get("value", "—"))

    disease_risks = payload.get("diseaseRisks") or payload.get("disease_risks") or []
    if disease_risks:
        y = _pdf_section_header(pdf, y, "Disease Risks")
        for r in disease_risks:
            if isinstance(r, dict):
                y = _pdf_kv(pdf, y, r.get("name", "Risk"), f"{r.get('risk', '—')}/100")

    recommendations = payload.get("recommendations") or []
    if recommendations:
        y = _pdf_section_header(pdf, y, "Recommendations")
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            title = rec.get("title") or rec.get("type") or "Recommendation"
            priority = rec.get("priority", "")
            desc = rec.get("description") or rec.get("action") or ""
            header = f"{title} [{priority}]" if priority else title
            y = _pdf_bullet(pdf, y, header)
            if desc:
                for line in textwrap.wrap(desc, width=74) or [desc]:
                    y = _pdf_ensure_space(pdf, y)
                    pdf.setFont("Helvetica", 9)
                    pdf.drawString(_PDF_LEFT + 30, y, line)
                    y -= _PDF_LINE - 2
                pdf.setFont("Helvetica", 10)
    return y


def _pdf_body_disease_risk(pdf, payload, y):
    risk_metrics = payload.get("riskMetrics") or payload.get("risk_metrics") or []
    if risk_metrics:
        y = _pdf_section_header(pdf, y, "Risk Overview")
        for m in risk_metrics:
            if isinstance(m, dict):
                y = _pdf_kv(pdf, y, m.get("label", "Risk"), m.get("value", "—"))

    alerts = payload.get("alerts") or payload.get("diseaseAlerts") or []
    if alerts:
        y = _pdf_section_header(pdf, y, "Disease Alerts")
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            name = alert.get("name") or "Unknown"
            severity = alert.get("severity") or "—"
            prob = alert.get("probability")
            prob_str = f"{prob}/100" if prob is not None else "—"
            y = _pdf_kv(pdf, y, name, f"Severity: {severity}  |  Probability: {prob_str}")
            symptoms = alert.get("symptoms")
            if symptoms:
                y = _pdf_bullet(pdf, y, f"Symptoms: {symptoms}")
            prevention = alert.get("prevention")
            if prevention:
                y = _pdf_bullet(pdf, y, f"Prevention: {prevention}")
            y -= 4

    vuln = payload.get("vulnerabilityFactors") or payload.get("vulnerability_factors") or []
    if vuln:
        y = _pdf_section_header(pdf, y, "Vulnerability Factors")
        for v in vuln:
            if isinstance(v, dict):
                factor = v.get("factor") or v.get("label") or "Factor"
                impact = v.get("impact") or v.get("value")
                val = f"{impact}/100" if isinstance(impact, (int, float)) else (impact or "—")
                y = _pdf_kv(pdf, y, factor, val)

    prev_recs = payload.get("preventionRecommendations") or payload.get("prevention_recommendations") or []
    if prev_recs:
        y = _pdf_section_header(pdf, y, "Prevention Recommendations")
        for rec in prev_recs:
            if isinstance(rec, str):
                y = _pdf_bullet(pdf, y, rec)
            elif isinstance(rec, dict):
                y = _pdf_bullet(pdf, y, rec.get("title") or rec.get("text") or str(rec))
    return y


def _pdf_body_fertilizer(pdf, payload, y):
    metrics = payload.get("ai_metrics") or payload.get("aiMetrics") or []
    if metrics:
        y = _pdf_section_header(pdf, y, "AI Recommendations")
        for m in metrics:
            if isinstance(m, dict):
                y = _pdf_kv(pdf, y, m.get("label", ""), m.get("value", "—"))

    schedule = payload.get("schedule") or []
    if schedule:
        y = _pdf_section_header(pdf, y, "Fertilizer Schedule")
        for s in schedule:
            if not isinstance(s, dict):
                continue
            week = s.get("week") or ""
            ftype = s.get("type") or "—"
            rate = s.get("rate") or "—"
            status = s.get("status") or ""
            line = f"{week}: {ftype}, {rate}"
            if status:
                line += f"  [{status}]"
            y = _pdf_bullet(pdf, y, line)

    guidelines = payload.get("guidelines") or []
    if guidelines:
        y = _pdf_section_header(pdf, y, "Guidelines")
        for g in guidelines:
            if isinstance(g, dict):
                title = g.get("title") or ""
                desc = g.get("text") or g.get("description") or ""
                if title:
                    y = _pdf_bullet(pdf, y, title)
                if desc:
                    for line in textwrap.wrap(desc, width=74) or [desc]:
                        y = _pdf_ensure_space(pdf, y)
                        pdf.setFont("Helvetica", 9)
                        pdf.drawString(_PDF_LEFT + 30, y, line)
                        y -= _PDF_LINE - 2
                    pdf.setFont("Helvetica", 10)
            elif isinstance(g, str):
                y = _pdf_bullet(pdf, y, g)

    activities = payload.get("recommended_activities") or []
    if activities:
        y = _pdf_section_header(pdf, y, "Recommended Activities")
        for act in activities:
            if isinstance(act, str):
                y = _pdf_bullet(pdf, y, act)
            elif isinstance(act, dict):
                y = _pdf_bullet(pdf, y, act.get("title") or act.get("text") or str(act))
    return y


def _pdf_body_weather(pdf, payload, y):
    current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    if current:
        y = _pdf_section_header(pdf, y, "Current Conditions")
        temp = current.get("temperature")
        if temp is not None:
            y = _pdf_kv(pdf, y, "Temperature", f"{temp}°C")
        desc = current.get("description")
        if desc:
            y = _pdf_kv(pdf, y, "Conditions", desc)
        humidity = current.get("humidity")
        if humidity is not None:
            y = _pdf_kv(pdf, y, "Humidity", f"{humidity}%")
        wind = current.get("wind_speed")
        if wind is not None:
            y = _pdf_kv(pdf, y, "Wind Speed", f"{wind} m/s")

    impacts = payload.get("impacts") or []
    if impacts:
        y = _pdf_section_header(pdf, y, "Weather Impacts on Crop")
        for imp in impacts:
            if not isinstance(imp, dict):
                continue
            label = imp.get("label") or "Impact"
            level = imp.get("level") or "—"
            percent = imp.get("percent")
            desc = imp.get("description") or ""
            val = level
            if percent is not None:
                val += f"  ({percent}%)"
            y = _pdf_kv(pdf, y, label, val)
            if desc:
                for line in textwrap.wrap(desc, width=76) or [desc]:
                    y = _pdf_ensure_space(pdf, y)
                    pdf.setFont("Helvetica-Oblique", 9)
                    pdf.drawString(_PDF_LEFT + 20, y, line)
                    y -= _PDF_LINE - 2
                pdf.setFont("Helvetica", 10)
                y -= 4
    return y


def _pdf_body_irrigation(pdf, payload, y):
    water_needs = payload.get("water_needs") or []
    if water_needs:
        y = _pdf_section_header(pdf, y, "Water Needs")
        for w in water_needs:
            if isinstance(w, dict):
                y = _pdf_kv(pdf, y, w.get("label", ""), w.get("value", "—"))

    schedule = payload.get("schedule") or []
    if schedule:
        y = _pdf_section_header(pdf, y, "Irrigation Schedule")
        for s in schedule:
            if isinstance(s, dict):
                period = s.get("period") or "—"
                rec = s.get("recommendation") or "—"
                y = _pdf_kv(pdf, y, period, rec)

    recs = payload.get("irrigation_recommendations") or []
    if recs:
        y = _pdf_section_header(pdf, y, "Recommendations")
        for r in recs:
            if not isinstance(r, dict):
                continue
            title = r.get("title") or "Recommendation"
            priority = r.get("priority") or ""
            desc = r.get("description") or ""
            header = f"{title} [{priority}]" if priority else title
            y = _pdf_bullet(pdf, y, header)
            if desc:
                for line in textwrap.wrap(desc, width=74) or [desc]:
                    y = _pdf_ensure_space(pdf, y)
                    pdf.setFont("Helvetica", 9)
                    pdf.drawString(_PDF_LEFT + 30, y, line)
                    y -= _PDF_LINE - 2
                pdf.setFont("Helvetica", 10)
    return y


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

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(_PDF_LEFT, 800, report.title)

    pdf.setFont("Helvetica", 10)
    pdf.drawString(_PDF_LEFT, 778, f"Type: {report.report_type}")
    field_name = report.field.name if report.field else "—"
    pdf.drawString(_PDF_LEFT, 762, f"Field: {field_name}")
    date_str = report.created_at.strftime("%B %d, %Y") if report.created_at else "—"
    pdf.drawString(_PDF_LEFT, 746, f"Date: {date_str}")

    pdf.setLineWidth(1)
    pdf.line(_PDF_LEFT, 738, _PDF_RIGHT, 738)

    y = 722
    summary_text = _resolve_report_summary(report)
    if summary_text:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(_PDF_LEFT, y, "Summary")
        y -= _PDF_LINE
        pdf.setFont("Helvetica", 10)
        for line in textwrap.wrap(summary_text, width=88):
            y = _pdf_ensure_space(pdf, y)
            pdf.drawString(_PDF_LEFT, y, line)
            y -= _PDF_LINE
        y -= 6

    payload = report.payload or {}
    rt = report.report_type
    if rt == "Crop Analysis":
        y = _pdf_body_crop_analysis(pdf, payload, y)
    elif rt == "Disease Risk":
        y = _pdf_body_disease_risk(pdf, payload, y)
    elif rt == "Fertilizer":
        y = _pdf_body_fertilizer(pdf, payload, y)
    elif rt == "Weather Analysis":
        y = _pdf_body_weather(pdf, payload, y)
    elif rt == "Irrigation":
        y = _pdf_body_irrigation(pdf, payload, y)

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
