from flask import Blueprint, make_response

seo_bp = Blueprint('seo', __name__)

@seo_bp.route('/sitemap.xml')
def sitemap():
    # 사이트의 주요 URL 목록 (AI Workspace의 34개 툴)
    pages = [
        '/', '/restaurant', '/bakery', '/cafe', '/lotto_scanner', '/clinic',
        '/course', '/travel', '/meetup', '/estate', '/message', '/english',
        '/shopping', '/shorts', '/youtube', '/youtube_summary', '/market',
        '/stock', '/prompt', '/lotto', '/chef', '/polisher', '/game_office',
        '/novel', '/tarot', '/saju', '/face', '/love', '/diet', '/diary',
        '/dream', '/therapist', '/fashion'
    ]
    
    base_url = 'https://ai-workspace-1.onrender.com'
    
    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    
    for page in pages:
        xml.append('  <url>')
        xml.append(f'    <loc>{base_url}{page}</loc>')
        xml.append('    <changefreq>weekly</changefreq>')
        xml.append('    <priority>0.8</priority>')
        xml.append('  </url>')
        
    xml.append('</urlset>')
    
    response = make_response('\\n'.join(xml))
    response.headers['Content-Type'] = 'application/xml'
    return response

@seo_bp.route('/robots.txt')
def robots():
    base_url = 'https://ai-workspace-1.onrender.com'
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        f"Sitemap: {base_url}/sitemap.xml"
    ]
    response = make_response('\\n'.join(lines))
    response.headers['Content-Type'] = 'text/plain'
    return response

@seo_bp.route('/googleddda9ca3018b8bd9.html')
def google_verification():
    return 'google-site-verification: googleddda9ca3018b8bd9.html'
