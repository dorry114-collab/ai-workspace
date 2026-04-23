from extensions import db
import uuid

class VisitorStat(db.Model):
    __tablename__ = 'visitor_stats'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), unique=True, nullable=False)
    today = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)

class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    author = db.Column(db.String(50), nullable=False, default="익명")
    text = db.Column(db.Text, nullable=False)
    date = db.Column(db.String(30), nullable=False)
