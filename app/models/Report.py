from datetime import datetime
from app import db


class Report(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    report_type = db.Column(db.String(50))
    file_path = db.Column(db.String(500))
    file_size = db.Column(db.Float)
    status = db.Column(db.String(50), default='Completed')
    summary = db.Column(db.Text)
    payload = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    pdf_download_count = db.Column(db.Integer, default=0)
    last_downloaded_at = db.Column(db.DateTime)

    field_id = db.Column(db.Integer, db.ForeignKey('fields.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    def _size_label(self):
        if self.file_size is None:
            return "—"
        return f"{self.file_size:.1f} MB"

    def to_dict(self, include_payload=False):
        field_name = self.field.name if self.field else "—"
        result = {
            "id": self.id,
            "name": self.title,
            "title": self.title,
            "field": field_name,
            "field_id": self.field_id,
            "type": self.report_type,
            "report_type": self.report_type,
            "date": self.created_at.strftime("%b %d, %Y") if self.created_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "size": self._size_label(),
            "file_size": self.file_size,
            "summary": self.summary,
            "user_id": self.user_id,

            "pdf_download_count": self.pdf_download_count or 0,
            "last_downloaded_at": self.last_downloaded_at.isoformat() if self.last_downloaded_at else None,
        }
        if include_payload:
            result["payload"] = self.payload
        return result
