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

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    # 카카오에서 넘어오는 고유 식별자 또는 이메일
    email = db.Column(db.String(120), unique=True, nullable=True) 
    nickname = db.Column(db.String(50), nullable=False)
    provider = db.Column(db.String(20), nullable=False, default='kakao') # kakao, google, etc.
    provider_id = db.Column(db.String(100), unique=True, nullable=False) # 각 플랫폼의 고유 ID
    points = db.Column(db.Integer, default=100) # 기본 제공 크레딧
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
