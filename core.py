from flask import Blueprint, render_template, request, jsonify
import os, datetime, uuid, traceback
from extensions import db, limiter
from models import VisitorStat, Comment

core_bp = Blueprint('core', __name__)

def get_stats():
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    stat = VisitorStat.query.filter_by(date=today_str).first()
    if not stat:
        # Check total
        total_stat = db.session.query(db.func.sum(VisitorStat.today)).scalar() or 0
        stat = VisitorStat(date=today_str, today=0, total=total_stat)
        db.session.add(stat)
        db.session.commit()
    return stat

def track_visitor():
    try:
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        stat = VisitorStat.query.filter_by(date=today_str).first()
        
        # Calculate new total
        total = db.session.query(db.func.sum(VisitorStat.today)).scalar() or 0
        
        if not stat:
            stat = VisitorStat(date=today_str, today=1, total=total + 1)
            db.session.add(stat)
        else:
            stat.today += 1
            stat.total = total + 1
            
        db.session.commit()
        return {"total": stat.total, "today": stat.today, "date": stat.date}
    except Exception as e:
        print(f"Error tracking visitor: {e}")
        return {"total": 0, "today": 0, "date": datetime.datetime.now().strftime('%Y-%m-%d')}

@core_bp.route('/')
def home():
    st = track_visitor()
    return render_template('home.html', stats=st)

@core_bp.route('/api/comments', methods=['GET', 'POST'])
def api_comments():
    if request.method == 'GET':
        comments = Comment.query.order_by(Comment.date.desc()).limit(100).all()
        comments_list = [{"id": c.id, "author": c.author, "text": c.text, "date": c.date} for c in comments]
        return jsonify({"success": True, "comments": comments_list})
        
    if request.method == 'POST':
        data = request.json
        author = data.get('author', '익명').strip()
        text = data.get('text', '').strip()
        if not author: author = "익명"
        if not text: return jsonify({"success": False, "error": "내용을 입력해주세요."})
        
        try:
            new_comment = Comment(
                author=author,
                text=text,
                date=datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            )
            db.session.add(new_comment)
            db.session.commit()
            
            # Fetch latest 100
            comments = Comment.query.order_by(Comment.date.desc()).limit(100).all()
            comments_list = [{"id": c.id, "author": c.author, "text": c.text, "date": c.date} for c in comments]
            
            return jsonify({"success": True, "comments": comments_list})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
