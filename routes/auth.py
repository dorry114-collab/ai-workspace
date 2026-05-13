import os
import requests
from flask import Blueprint, redirect, request, session, url_for, jsonify
from extensions import db
from models import User

auth_bp = Blueprint('auth', __name__)

KAKAO_CLIENT_ID = os.environ.get('KAKAO_CLIENT_ID', '') # REST API 키
KAKAO_REDIRECT_URI = os.environ.get('KAKAO_REDIRECT_URI', 'https://ai-workspace-1.onrender.com/auth/kakao/callback')

@auth_bp.route('/kakao')
def kakao_login():
    """카카오 로그인 창으로 리다이렉트"""
    if not KAKAO_CLIENT_ID:
        return "카카오 로그인 키가 설정되지 않았습니다.", 500
    
    kakao_oauth_url = f"https://kauth.kakao.com/oauth/authorize?client_id={KAKAO_CLIENT_ID}&redirect_uri={KAKAO_REDIRECT_URI}&response_type=code"
    return redirect(kakao_oauth_url)

@auth_bp.route('/kakao/callback')
def kakao_callback():
    """카카오 인증 완료 후 리다이렉트 되는 콜백 URL"""
    code = request.args.get('code')
    if not code:
        return "인증 코드가 없습니다.", 400
        
    # 1. 코드로 액세스 토큰 받기
    token_request_url = "https://kauth.kakao.com/oauth/token"
    token_payload = {
        "grant_type": "authorization_code",
        "client_id": KAKAO_CLIENT_ID,
        "redirect_uri": KAKAO_REDIRECT_URI,
        "code": code
    }
    
    token_res = requests.post(token_request_url, data=token_payload)
    if token_res.status_code != 200:
        return f"토큰 발급 실패: {token_res.text}", 400
        
    access_token = token_res.json().get('access_token')
    
    # 2. 액세스 토큰으로 사용자 정보 가져오기
    profile_url = "https://kapi.kakao.com/v2/user/me"
    headers = {"Authorization": f"Bearer {access_token}"}
    profile_res = requests.get(profile_url, headers=headers)
    
    if profile_res.status_code != 200:
        return f"프로필 가져오기 실패: {profile_res.text}", 400
        
    profile_data = profile_res.json()
    kakao_id = str(profile_data.get('id'))
    properties = profile_data.get('properties', {})
    kakao_account = profile_data.get('kakao_account', {})
    
    nickname = properties.get('nickname', '사용자')
    email = kakao_account.get('email', None)
    
    # 3. DB에 사용자 정보 저장 또는 업데이트
    user = User.query.filter_by(provider='kakao', provider_id=kakao_id).first()
    
    if not user:
        # 새 사용자 생성 (가입 축하 포인트 100 지급)
        user = User(
            provider='kakao',
            provider_id=kakao_id,
            nickname=nickname,
            email=email,
            points=100
        )
        db.session.add(user)
        db.session.commit()
    elif user.nickname != nickname:
        # 닉네임이 바뀌었으면 업데이트
        user.nickname = nickname
        db.session.commit()
        
    # 4. 세션에 로그인 정보 저장
    session['user_id'] = user.id
    session['user_nickname'] = user.nickname
    session['user_points'] = user.points
    
    # 로그인 완료 후 홈으로 이동
    return redirect(url_for('core.index'))

@auth_bp.route('/logout')
def logout():
    """로그아웃 처리 (세션 초기화)"""
    session.clear()
    return redirect(url_for('core.index'))

@auth_bp.route('/me')
def get_user_info():
    """현재 로그인한 유저 정보를 반환하는 API (AJAX용)"""
    if 'user_id' not in session:
        return jsonify({'logged_in': False})
        
    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return jsonify({'logged_in': False})
        
    return jsonify({
        'logged_in': True,
        'id': user.id,
        'nickname': user.nickname,
        'points': user.points
    })
