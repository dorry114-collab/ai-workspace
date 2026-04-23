import json
import os
from app_new import create_app
from extensions import db
from models import VisitorStat, Comment

app = create_app()

with app.app_context():
    db.create_all()

    # Migrate stats
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            stat = VisitorStat.query.filter_by(date=data.get('date')).first()
            if not stat:
                new_stat = VisitorStat(
                    date=data.get('date', '2024-01-01'),
                    today=data.get('today', 0),
                    total=data.get('total', 0)
                )
                db.session.add(new_stat)
                db.session.commit()
                print("Stats migrated.")
        except Exception as e:
            print("Failed to migrate stats:", e)

    # Migrate comments
    if os.path.exists('comments.json'):
        try:
            with open('comments.json', 'r', encoding='utf-8') as f:
                comments = json.load(f)
                
            for c in comments:
                if not Comment.query.get(c.get('id')):
                    new_comment = Comment(
                        id=c.get('id'),
                        author=c.get('author', '익명'),
                        text=c.get('text', ''),
                        date=c.get('date', '')
                    )
                    db.session.add(new_comment)
            db.session.commit()
            print(f"Migrated {len(comments)} comments.")
        except Exception as e:
            print("Failed to migrate comments:", e)

print("Migration completed.")
