from datetime import datetime, timezone
from extensions import db


class Url(db.Model):
    __tablename__ = "urls"

    id = db.Column(db.BigInteger, primary_key=True)
    short_code = db.Column(db.String(10), unique=True, nullable=False, index=True)
    original_url = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    clicks = db.relationship(
        "Click", backref="url", lazy="dynamic", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Url {self.short_code} -> {self.original_url}>"


class Click(db.Model):
    __tablename__ = "clicks"

    id = db.Column(db.BigInteger, primary_key=True)
    url_id = db.Column(
        db.BigInteger, db.ForeignKey("urls.id"), nullable=False, index=True
    )
    clicked_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    referrer = db.Column(db.Text)

    def __repr__(self):
        return f"<Click url_id={self.url_id} at={self.clicked_at}>"