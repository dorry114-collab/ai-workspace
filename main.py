from flask import Flask
import os
import ssl

# --- 로컬 API 키 주입 로직 ---
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()
# -----------------------------

from extensions import db, limiter
from routes.core import core_bp
from routes.stock import stock_bp
from routes.tools import tools_bp
from routes.scanner import scanner_bp
from routes.games_life import games_life_bp
from routes.seo import seo_bp

# Global SSL setup from original main.py
ssl._create_default_https_context = ssl._create_unverified_context

def create_app():
    app = Flask(__name__)
    
    # Configure Database
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize extensions
    db.init_app(app)
    # Global Rate limit: 2000 per day, 500 per hour
    limiter.init_app(app)
    
    # Create tables
    with app.app_context():
        import models
        db.create_all()
        
    # Register blueprints
    app.register_blueprint(core_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(tools_bp)
    app.register_blueprint(scanner_bp)
    app.register_blueprint(games_life_bp)
    app.register_blueprint(seo_bp)
    
    @app.after_request
    def add_header(response):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
        return response
    
    return app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port, debug=False)
