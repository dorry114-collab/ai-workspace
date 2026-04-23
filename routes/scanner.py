from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd
import numpy as np
import datetime
from sklearn.linear_model import LinearRegression
import urllib.request
import urllib.parse
import ssl
import requests
import FinanceDataReader as fdr
import yt_dlp
import threading
import webbrowser
import os
import tempfile
import uuid
import re
import math
import base64
from io import BytesIO
import traceback
import json
import asyncio
import edge_tts
from PIL import Image as PILImage, ImageDraw, ImageFont

app = Flask(__name__)
from flask import Blueprint, render_template, request, jsonify
import os, json, datetime, uuid, urllib.parse, urllib.request, traceback
from extensions import db, limiter

scanner_bp = Blueprint('scanner', __name__)

@scanner_bp.route('/restaurant')
def restaurant():
    import os
    return render_template('restaurant.html', google_maps_api_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))


@scanner_bp.route('/api/restaurant/search', methods=['POST'])
def restaurant_search():
    data = request.json
    address = data.get('address', '').strip()
    radius = int(data.get('radius', 5000))
    
    lat = data.get('lat')
    lng = data.get('lng')
    
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "서비스 설정 오류: 카카오 REST API 키가 환경 변수에 등록되지 않았습니다."})
        
    if not address and not (lat and lng):
        return jsonify({"success": False, "error": "주소나 위치 정보가 없습니다."})
        
    headers = {"Authorization": f"KakaoAK {api_key}"}
    
    try:
        if lat and lng:
            x = str(lng)
            y = str(lat)
        else:
            geo_url = f"https://dapi.kakao.com/v2/local/search/address.json?query={urllib.parse.quote(address)}"
            geo_resp = requests.get(geo_url, headers=headers)
            geo_data = geo_resp.json()
            
            if not geo_data.get('documents'):
                kw_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(address)}"
                kw_resp = requests.get(kw_url, headers=headers)
                kw_data = kw_resp.json()
                if kw_data.get('documents'):
                    geo_data = kw_data
                
            if not geo_data.get('documents'):
                return jsonify({"success": False, "error": f"검색된 주소나 장소가 없습니다. (Kakao API 응답: {geo_data})"})
                
            x = geo_data['documents'][0]['x']
            y = geo_data['documents'][0]['y']
        
        # 2. 좌표 기준 음식점(FD6) 검색
        places = []
        for page in range(1, 5):  # 최대 4페이지(60개)로 확장
            cat_url = f"https://dapi.kakao.com/v2/local/search/category.json?category_group_code=FD6&x={x}&y={y}&radius={radius}&page={page}"
            cat_resp = requests.get(cat_url, headers=headers)
            cat_data = cat_resp.json()
            docs = cat_data.get('documents', [])
            places.extend(docs)
            if cat_data.get('meta', {}).get('is_end', True):
                break
                
        if not places:
            return jsonify({"success": False, "error": "해당 반경 내에 검색된 음식점이 없습니다."})
            
        # 3. 카테고리 단순화 및 정리
        results = []
        import concurrent.futures
        
        def scrape_place(p):
            pid = p.get('id')
            p_name = p.get('place_name')
            p_url = p.get('place_url')
            full_cat = p.get('category_name', '')
            dist = int(p.get('distance', 0))
            
            # 카테고리 매핑 (한식, 중식, 일식, 양식, 카페, 기타)
            cat_simplified = "기타"
            if "한식" in full_cat: cat_simplified = "한식"
            elif "중식" in full_cat: cat_simplified = "중식"
            elif "일식" in full_cat: cat_simplified = "일식"
            elif "양식" in full_cat: cat_simplified = "양식"
            elif "카페" in full_cat or "커피" in full_cat: cat_simplified = "카페"
            elif "분식" in full_cat: cat_simplified = "분식"
            
            item = {
                'id': pid,
                'name': p_name,
                'category': cat_simplified,
                'full_category': full_cat,
                'distance': dist,
                'address': p.get('road_address_name') or p.get('address_name'),
                'phone': p.get('phone', ''),
                'x': p.get('x'),
                'y': p.get('y'),
                'url': p_url,
                'rating': "N/A",
                'total_ratings': 0,
                'place_id': None,
                'photo_url': None,
                'is_open': None
            }
            
            # 1. (제거됨) 카카오맵 로컬 스크래핑은 카카오 측의 트래픽 차단으로 인해 제거됨.
            
            # 2. 구글 Places API 연동하여 별점 가져오기 (키가 있을 경우에만)
            item['total_ratings'] = 0
            google_api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
            if google_api_key:
                try:
                    search_query = f"{p_name} {item['address'].split()[0]}" # 예: "스타벅스 대구" (너무 길면 못찾을 수 있으므로 시도 이름만 첨부)
                    g_url = f"https://maps.googleapis.com/maps/api/place/findplacefromtext/json?input={urllib.parse.quote(search_query)}&inputtype=textquery&fields=place_id,rating,user_ratings_total,photos,opening_hours&locationbias=point:{p.get('y')},{p.get('x')}&key={google_api_key}"
                    g_resp = requests.get(g_url, timeout=2.0).json()
                    
                    if g_resp.get('status') == 'OK' and g_resp.get('candidates'):
                        cand = g_resp['candidates'][0]
                        rating = cand.get('rating')
                        total_ratings = cand.get('user_ratings_total', 0)
                        
                        item['total_ratings'] = total_ratings
                        item['place_id'] = cand.get('place_id')
                        
                        if 'opening_hours' in cand:
                            item['is_open'] = cand['opening_hours'].get('open_now')
                            
                        if 'photos' in cand and cand['photos']:
                            photo_ref = cand['photos'][0].get('photo_reference')
                            item['photo_url'] = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photo_reference={photo_ref}&key={google_api_key}"
                        
                        # 리뷰가 10개 이상일 때만 유효한 별점으로 인정
                        if rating and total_ratings >= 10:
                            item['rating'] = str(rating)
                            item['trust_score'] = int(float(rating) * total_ratings)
                        else:
                            item['rating'] = "평가 부족"
                            item['trust_score'] = 0
                except Exception as e:
                    pass
            
            return item

        # 병렬 스크래핑 처리
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            scraped_places = list(executor.map(scrape_place, places[:50])) # 최대 30개에서 50개로 확장
            
        results = sorted(scraped_places, key=lambda x: x['distance'])
        
        return jsonify({
            "success": True, 
            "data": results, 
            "center": {"x": x, "y": y}
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": f"검색 중 오류 발생: {str(e)}"})


@scanner_bp.route("/api/geocode", methods=["POST"])
def geocode():
    data = request.json
    lat = data.get("lat")
    lng = data.get("lng")
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key or not lat or not lng:
        return jsonify({"success": False, "error": "API 키 또는 좌표 정보 누락"})
    
    url = f"https://dapi.kakao.com/v2/local/geo/coord2regioncode.json?x={lng}&y={lat}"
    try:
        import requests
        resp = requests.get(url, headers={"Authorization": f"KakaoAK {api_key}"}).json()
        docs = resp.get("documents", [])
        if docs:
            # 법정동 혹은 행정동 기준 주소 리턴
            for d in docs:
                if d.get("region_type") == "B":  # 법정동
                    return jsonify({"success": True, "address": d.get("address_name")})
            return jsonify({"success": True, "address": docs[0].get("address_name")})
        return jsonify({"success": False, "error": "위치 변환 결과가 없습니다."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@scanner_bp.route("/api/restaurant/summary", methods=["POST"])
def restaurant_summary():
    try:
        data = request.json or {}
        place_id = data.get("place_id")
        place_type = data.get("place_type", "맛집")
        purpose = data.get("purpose", "일반(상관없음)")
        
        import os
        google_api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
        
        if not place_id or not google_api_key:
            return jsonify({"success": False, "error": "요청 정보가 올바르지 않거나 구글 API 키가 세팅되지 않았습니다."})
            
        det_url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=reviews&language=ko&key={google_api_key}"
        import requests
        resp = requests.get(det_url, timeout=10).json()
        reviews = resp.get("result", {}).get("reviews", [])
        
        if not reviews:
            return jsonify({"success": True, "summary": {"summary": "아직 리뷰가 충분하지 않아 요약할 수 없습니다."}})
            
        review_texts = [r.get("text") for r in reviews if r.get("text")]
        combined_text = "\n".join(review_texts[:5])
        
        if not combined_text.strip():
            return jsonify({"success": True, "summary": {"summary": "아직 텍스트 리뷰가 없어 요약할 수 없습니다."}})
            
        import os
        gemini_api_key = os.environ.get("GEMINI_API_KEY")
        
        if not gemini_api_key:
            return jsonify({"success": False, "error": "AI API 키(Gemini)가 세팅되지 않았습니다."})
            
        system_instructions = f"""당신은 방문 목적에 맞춰 로컬 리뷰를 완벽히 분석해주는 AI 맛집 가이드입니다.
사용자의 이번 대상은 '{place_type}' 이며, 방문 목적은 '{purpose}'입니다.
제공된 실제 방문자 리뷰 5개를 분석하여 반드시 아래의 JSON 규격으로만 응답해야 합니다. 다른 설명 없이 순수 JSON만 출력하세요.

{{
  "target_score": <유저의 목적 '{purpose}'에 100점 만점 기준으로 얼마나 적합한지를 나타내는 점수 (정수), 리뷰를 바탕으로 깐깐하게 평가할 것>,
  "recent_vibe": "<가장 최근 리뷰의 감정선을 바탕으로 최근 폼/민심을 요약한 한줄 평 (예: 🚀 최근 폼 미쳤음 극찬, ⚠️ 최근 불친절 리뷰 급증 등 이모지 필수)>",
  "hashtags": ["<시그니처 메뉴 이름이 들어간 해시태그>", "<강조된 분위기 태그 2>", "<단점이나 주차 등 태그 3>"],
  "summary": "<방문 목적 '{purpose}' 관점에서 꼭 참고해야 할 유용한 2~3줄 요약 및 조언. 친근하고 생동감 있게 작성할 것.>"
}}
"""
        prompt = f"[리뷰 데이터]:\n{combined_text}"
        
        import google.generativeai as genai
        import json
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system_instructions)
        
        response = model.generate_content(prompt, request_options={'timeout': 15})
        
        res_text = response.text.strip()
        if "```json" in res_text:
             res_text = res_text.split("```json")[1].split("```")[0].strip()
        elif "```" in res_text:
             res_text = res_text.split("```")[1].strip()
             
        try:
            parsed_data = json.loads(res_text)
            return jsonify({"success": True, "summary": parsed_data})
        except json.JSONDecodeError:
            print("FAILED JSON PARSE:", res_text)
            return jsonify({"success": False, "error": "AI가 올바른 JSON 데이터를 반환하지 않았습니다."})
        
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print("===== [AI SUMMARY ERROR] =====")
        print(err_msg)
        error_str = str(e)
        if "429" in error_str or "quota" in error_str.lower() or "exceeded" in error_str.lower():
            return jsonify({"success": False, "error": "AI 호출 한도 초과: 구글 제미나이 무료 제공량(1분 15회)이 초과되었습니다. 잠시 후 다시 시도해주세요."})
        return jsonify({"success": False, "error": f"AI 분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요. ({error_str})" })


@scanner_bp.route("/api/restaurant/chat", methods=["POST"])
def restaurant_chat():
    try:
        data = request.json or {}
        place_id = data.get("place_id")
        question = data.get("question")
        import os
        google_api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
        
        if not place_id or not google_api_key or not question:
            return jsonify({"success": False, "error": "요청 정보가 올바르지 않거나 질문이 없습니다."})
            
        det_url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=reviews&language=ko&key={google_api_key}"
        import requests
        resp = requests.get(det_url).json()
        reviews = resp.get("result", {}).get("reviews", [])
        
        if not reviews:
            return jsonify({"success": True, "answer": "아직 리뷰가 등록되지 않아 답변할 수 없습니다."})
            
        review_texts = [r.get("text") for r in reviews if r.get("text")]
        combined_text = "\n".join(review_texts[:5])
        
        if not combined_text.strip():
            return jsonify({"success": True, "answer": "텍스트 리뷰가 없어 구체적인 답변을 드릴 수 없습니다."})
            
        import os
        groq_api_key = os.environ.get("GROQ_API_KEY")
        gemini_api_key = os.environ.get("GEMINI_API_KEY")
        
        if not groq_api_key and not gemini_api_key:
            return jsonify({"success": False, "error": "AI API 키(Groq 또는 Gemini)가 세팅되지 않았습니다."})
            
        prompt = f"""다음은 이 가게의 최근 방문자 리뷰입니다:
{combined_text}

사용자의 질문: {question}

위 리뷰 내용을 바탕으로 사용자의 질문에 친절하게 답변해주세요. 리뷰에 관련된 정보가 아예 없다면 '리뷰 내용에서는 해당 정보를 찾을 수 없습니다.' 라고 답변해 주세요. (2~3줄 이내로 간결하게 답변)"""

        # 1. 빠른 Groq API 우선 시도
        if groq_api_key:
            sys_role = "당신은 리뷰 바탕으로 질문에 대답해주는 친절한 한국인 가이드입니다. 반드시 자연스러운 한국어 문장으로만 대답하세요. 외계어나 한자, 베트남어, 이상한 글자가 섞이면 안 됩니다."
            success, text = _call_groq(groq_api_key, prompt, system_role=sys_role)
            if success:
                return jsonify({"success": True, "answer": text})
            else:
                if not gemini_api_key:
                    return jsonify({"success": False, "error": f"Groq 통신 실패: {text}"})

        # 2. Gemini fallback
        import google.generativeai as genai
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        response = model.generate_content(prompt, request_options={'timeout': 15})
        return jsonify({"success": True, "answer": response.text.strip()})
        
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print("===== [AI CHAT ERROR] =====")
        print(err_msg)
        error_str = str(e)
        if "429" in error_str or "quota" in error_str.lower() or "exceeded" in error_str.lower():
            return jsonify({"success": False, "error": "AI 호출 한도 초과: 약 1분 뒤에 다시 시도해주세요. (단기간 사용량 초과)"})
        return jsonify({"success": False, "error": f"AI 답변 중 오류가 발생했습니다. ({error_str})"})


@scanner_bp.route('/bakery')
def bakery():
    import os
    return render_template('bakery.html', google_maps_api_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))


@scanner_bp.route('/api/bakery/search', methods=['POST'])
def bakery_search():
    data = request.json
    address = data.get('address', '').strip()
    radius = data.get('radius', '3000')
    import os, urllib.parse, requests
    from flask import jsonify
    
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "서비스 설정 오류: 카카오 REST API 키가 환경 변수에 등록되지 않았습니다."})
        
    if not address:
        return jsonify({"success": False, "error": "지역명을 입력해주세요."})
        
    headers = {"Authorization": f"KakaoAK {api_key}"}
    
    try:
        # 1. 주소 -> 위경도 변환
        geo_url = f"https://dapi.kakao.com/v2/local/search/address.json?query={urllib.parse.quote(address)}"
        geo_resp = requests.get(geo_url, headers=headers).json()
        
        if not geo_resp.get('documents'):
            geo_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(address)}"
            geo_resp = requests.get(geo_url, headers=headers).json()
            
        if not geo_resp.get('documents'):
            return jsonify({"success": False, "error": "해당 주소나 지역을 찾을 수 없습니다."})
            
        x = geo_resp['documents'][0]['x']
        y = geo_resp['documents'][0]['y']

        search_query = f"{address} 빵집"
        places = []
        for page in range(1, 4):  # 카카오 키워드 검색 최대 3페이지(45개)
            cat_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote('빵집')}&x={x}&y={y}&radius={radius}&page={page}"
            cat_resp = requests.get(cat_url, headers=headers)
            cat_data = cat_resp.json()
            docs = cat_data.get('documents', [])
            
            # 파리바게뜨, 뚜레쥬르 등의 대형 프랜차이즈 제외
            ignore_keywords = ['파리바게', '뚜레쥬', '뚜레주', '파리크라상', '던킨', '배스킨', '베스킨', '크리스피크림']
            for d in docs:
                p_name = d.get('place_name', '')
                if not any(k in p_name for k in ignore_keywords):
                    places.append(d)
                    
            if cat_data.get('meta', {}).get('is_end', True):
                break
                
        if not places:
            return jsonify({"success": False, "error": f"'{search_query}'(으)로 검색된 결과가 없습니다."})
            
        results = []
        import concurrent.futures
        
        def scrape_place(p):
            pid = p.get('id')
            p_name = p.get('place_name')
            p_url = p.get('place_url')
            full_cat = p.get('category_name', '')
            dist_str = p.get('distance', '0')
            dist = int(dist_str) if dist_str else 0
            
            # 제과,베이커리 분류 단순화
            cat_simplified = "기타"
            if "식빵" in p_name or "식빵" in full_cat: cat_simplified = "식빵"
            elif "케이크" in p_name or "케익" in p_name: cat_simplified = "디저트/케이크"
            elif "도넛" in p_name or "도너츠" in p_name: cat_simplified = "도넛/마카롱"
            elif "베이커리" in p_name or "제과점" in full_cat: cat_simplified = "베이커리"
            elif "디저트" in full_cat: cat_simplified = "디저트/케이크"
            else: cat_simplified = "동네빵집"
            
            item = {
                'id': pid,
                'name': p_name,
                'category': cat_simplified,
                'full_category': full_cat,
                'distance': dist,
                'address': p.get('road_address_name') or p.get('address_name'),
                'phone': p.get('phone', ''),
                'x': p.get('x'),
                'y': p.get('y'),
                'url': p_url,
                'rating': "N/A",
                'total_ratings': 0,
                'place_id': None,
                'photo_url': None,
                'is_open': None,
                'trust_score': 0
            }
            
            google_api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
            if google_api_key:
                try:
                    search_query = f"{p_name} {item['address'].split()[0]}" 
                    g_url = f"https://maps.googleapis.com/maps/api/place/findplacefromtext/json?input={urllib.parse.quote(search_query)}&inputtype=textquery&fields=place_id,rating,user_ratings_total,photos,opening_hours&locationbias=point:{p.get('y')},{p.get('x')}&key={google_api_key}"
                    import requests
                    g_resp = requests.get(g_url, timeout=2.0).json()
                    
                    if g_resp.get('status') == 'OK' and g_resp.get('candidates'):
                        cand = g_resp['candidates'][0]
                        rating = cand.get('rating')
                        total_ratings = cand.get('user_ratings_total', 0)
                        
                        item['total_ratings'] = total_ratings
                        item['place_id'] = cand.get('place_id')
                        
                        if 'opening_hours' in cand:
                            item['is_open'] = cand['opening_hours'].get('open_now')
                            
                        if 'photos' in cand and cand['photos']:
                            photo_ref = cand['photos'][0].get('photo_reference')
                            item['photo_url'] = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photo_reference={photo_ref}&key={google_api_key}"
                        
                        if rating and total_ratings >= 10:
                            item['rating'] = str(rating)
                            item['trust_score'] = int(float(rating) * total_ratings)
                        else:
                            item['rating'] = "평가 부족"
                            item['trust_score'] = 0
                except Exception as e:
                    pass
            
            return item

        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            scraped_places = list(executor.map(scrape_place, places[:50]))
            
        results = sorted(scraped_places, key=lambda k: k.get('trust_score', 0), reverse=True)
        
        return jsonify({
            "success": True, 
            "data": results, 
            "center": None
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": f"검색 중 오류 발생: {str(e)}"})


@scanner_bp.route('/cafe')
def cafe():
    import os
    return render_template('cafe.html', google_maps_api_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))


@scanner_bp.route('/api/cafe/search', methods=['POST'])
def cafe_search():
    data = request.json
    address = data.get('address', '').strip()
    radius = data.get('radius', '3000')
    import os, urllib.parse, requests
    from flask import jsonify
    
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "서비스 설정 오류: 카카오 REST API 키가 환경 변수에 등록되지 않았습니다."})
        
    if not address:
        return jsonify({"success": False, "error": "지역명을 입력해주세요."})
        
    headers = {"Authorization": f"KakaoAK {api_key}"}
    
    try:
        # 1. 주소 -> 위경도 변환
        geo_url = f"https://dapi.kakao.com/v2/local/search/address.json?query={urllib.parse.quote(address)}"
        geo_resp = requests.get(geo_url, headers=headers).json()
        
        if not geo_resp.get('documents'):
            geo_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(address)}"
            geo_resp = requests.get(geo_url, headers=headers).json()
            
        if not geo_resp.get('documents'):
            return jsonify({"success": False, "error": "해당 주소나 지역을 찾을 수 없습니다."})
            
        x = geo_resp['documents'][0]['x']
        y = geo_resp['documents'][0]['y']

        # CE7(카페) 카테고리 검색
        places = []
        for page in range(1, 4):  # 카카오 키워드 검색 최대 3페이지(45개)
            cat_url = f"https://dapi.kakao.com/v2/local/search/category.json?category_group_code=CE7&x={x}&y={y}&radius={radius}&page={page}"
            cat_resp = requests.get(cat_url, headers=headers)
            cat_data = cat_resp.json()
            docs = cat_data.get('documents', [])
            
            # 대형 프랜차이즈 카페 제외
            ignore_keywords = ['스타벅스', '투썸', '이디야', '메가커피', '메가MGC', '컴포즈', '빽다방', '할리스', '파스쿠찌', '엔제리너스', '탐앤탐스', '폴바셋', '커피빈']
            for d in docs:
                p_name = d.get('place_name', '')
                if not any(k in p_name for k in ignore_keywords):
                    places.append(d)
                    
            if cat_data.get('meta', {}).get('is_end', True):
                break
                
        if not places:
            return jsonify({"success": False, "error": f"'{search_query}'(으)로 검색된 결과가 없습니다."})
            
        results = []
        import concurrent.futures
        
        def scrape_place(p):
            pid = p.get('id')
            p_name = p.get('place_name')
            p_url = p.get('place_url')
            full_cat = p.get('category_name', '')
            dist_str = p.get('distance', '0')
            dist = int(dist_str) if dist_str else 0
            
            # 카페 분류 단순화
            cat_simplified = "기타"
            if "로스터리" in p_name or "로스팅" in p_name: cat_simplified = "로스터리"
            elif "에스프레소" in p_name or "에스프레소" in full_cat: cat_simplified = "에스프레소"
            elif "디저트" in full_cat or "케이크" in p_name: cat_simplified = "디저트/케이크"
            else: cat_simplified = "동네카페"
            
            item = {
                'id': pid,
                'name': p_name,
                'category': cat_simplified,
                'full_category': full_cat,
                'distance': dist,
                'address': p.get('road_address_name') or p.get('address_name'),
                'phone': p.get('phone', ''),
                'x': p.get('x'),
                'y': p.get('y'),
                'url': p_url,
                'rating': "N/A",
                'total_ratings': 0,
                'place_id': None,
                'photo_url': None,
                'is_open': None,
                'trust_score': 0
            }
            
            google_api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
            if google_api_key:
                try:
                    search_query = f"{p_name} {item['address'].split()[0]}" 
                    g_url = f"https://maps.googleapis.com/maps/api/place/findplacefromtext/json?input={urllib.parse.quote(search_query)}&inputtype=textquery&fields=place_id,rating,user_ratings_total,photos,opening_hours&locationbias=point:{p.get('y')},{p.get('x')}&key={google_api_key}"
                    import requests
                    g_resp = requests.get(g_url, timeout=2.0).json()
                    
                    if g_resp.get('status') == 'OK' and g_resp.get('candidates'):
                        cand = g_resp['candidates'][0]
                        rating = cand.get('rating')
                        total_ratings = cand.get('user_ratings_total', 0)
                        
                        item['total_ratings'] = total_ratings
                        item['place_id'] = cand.get('place_id')
                        
                        if 'opening_hours' in cand:
                            item['is_open'] = cand['opening_hours'].get('open_now')
                            
                        if 'photos' in cand and cand['photos']:
                            photo_ref = cand['photos'][0].get('photo_reference')
                            item['photo_url'] = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photo_reference={photo_ref}&key={google_api_key}"
                        
                        if rating and total_ratings >= 10:
                            item['rating'] = str(rating)
                            item['trust_score'] = int(float(rating) * total_ratings)
                        else:
                            item['rating'] = "평가 부족"
                            item['trust_score'] = 0
                except Exception as e:
                    pass
            
            return item

        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            scraped_places = list(executor.map(scrape_place, places[:50]))
            
        results = sorted(scraped_places, key=lambda k: k.get('trust_score', 0), reverse=True)
        
        return jsonify({
            "success": True, 
            "data": results, 
            "center": None
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": f"검색 중 오류 발생: {str(e)}"})


@scanner_bp.route('/clinic')
def clinic():
    import os
    return render_template('clinic.html', google_maps_api_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))


@scanner_bp.route('/api/clinic/search', methods=['POST'])
def clinic_search():
    data = request.json
    address = data.get('address', '').strip()
    radius = data.get('radius', '3000')
    import os, urllib.parse, requests
    from flask import jsonify
    
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "서비스 설정 오류: 카카오 REST API 키가 환경 변수에 등록되지 않았습니다."})
        
    if not address:
        return jsonify({"success": False, "error": "지역명 또는 주소를 입력해주세요."})
        
    headers = {"Authorization": f"KakaoAK {api_key}"}
    
    try:
        # 1. 주소 -> 위경도 변환
        geo_url = f"https://dapi.kakao.com/v2/local/search/address.json?query={urllib.parse.quote(address)}"
        geo_resp = requests.get(geo_url, headers=headers).json()
        
        if not geo_resp.get('documents'):
            geo_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(address)}"
            geo_resp = requests.get(geo_url, headers=headers).json()
            
        if not geo_resp.get('documents'):
            return jsonify({"success": False, "error": "해당 주소나 지역을 찾을 수 없습니다."})
            
        x = geo_resp['documents'][0]['x']
        y = geo_resp['documents'][0]['y']
        
        # 2. HP8(병원) 카테고리 반경 검색 + '한의원' 키워드 병행 검색
        places = []
        seen_ids = set()
        
        # (1) HP8 카테고리 검색
        for page in range(1, 3):  # 최대 2페이지(30개)로 줄임 (시간 단축)
            cat_url = f"https://dapi.kakao.com/v2/local/search/category.json?category_group_code=HP8&x={x}&y={y}&radius={radius}&page={page}"
            cat_resp = requests.get(cat_url, headers=headers)
            cat_data = cat_resp.json()
            docs = cat_data.get('documents', [])
            
            ignore_keywords = ["요양", "동물", "수의", "대학병원", "대학교병원", "의료원", "보건소"]
            for d in docs:
                p_name = d.get('place_name', '')
                pid = d.get('id')
                if pid not in seen_ids and not any(k in p_name for k in ignore_keywords):
                    places.append(d)
                    seen_ids.add(pid)
                    
            if cat_data.get('meta', {}).get('is_end', True):
                break
        
        # (2) 한의원 키워드 검색 (HP8에 안 잡히는 경우가 많음)
        for page in range(1, 3):  # 최대 2페이지(30개)
            kw_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote('한의원')}&x={x}&y={y}&radius={radius}&page={page}"
            kw_resp = requests.get(kw_url, headers=headers)
            kw_data = kw_resp.json()
            docs = kw_data.get('documents', [])
            
            for d in docs:
                p_name = d.get('place_name', '')
                pid = d.get('id')
                if pid not in seen_ids and "한의원" in p_name:
                    places.append(d)
                    seen_ids.add(pid)
                    
            if kw_data.get('meta', {}).get('is_end', True):
                break
                
        if not places:
            return jsonify({"success": False, "error": "해당 지역 근처에 검색된 병원/클리닉이 없습니다."})
            
        import concurrent.futures
        
        def scrape_place(p):
            pid = p.get('id')
            p_name = p.get('place_name')
            p_url = p.get('place_url')
            full_cat = p.get('category_name', '')
            dist_str = p.get('distance', '0')
            dist = int(dist_str) if dist_str else 0
            
            # 카테고리 단순화
            cat_simplified = "기타 병의원"
            if "치과" in p_name or "치과" in full_cat: cat_simplified = "치과"
            elif "피부과" in p_name or "성형외과" in p_name: cat_simplified = "피부과/성형"
            elif "내과" in p_name or "이비인후과" in p_name: cat_simplified = "내과/이비인후과"
            elif "소아과" in p_name or "소아" in full_cat: cat_simplified = "소아과"
            elif "안과" in p_name or "정형외과" in p_name or "통증" in p_name or "재활" in p_name: cat_simplified = "안과/정형외과"
            elif "한의원" in p_name or "한방" in p_name or "한의" in full_cat: cat_simplified = "한의원"
            else: cat_simplified = "기타 병의원"
            
            item = {
                'id': pid,
                'name': p_name,
                'category': cat_simplified,
                'full_category': full_cat,
                'distance': dist,
                'address': p.get('road_address_name') or p.get('address_name'),
                'phone': p.get('phone', ''),
                'x': p.get('x'),
                'y': p.get('y'),
                'url': p_url,
                'rating': "N/A",
                'total_ratings': 0,
                'place_id': None,
                'photo_url': None,
                'is_open': None,
                'trust_score': 0
            }
            
            google_api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
            if google_api_key:
                try:
                    search_query = f"{p_name} {item['address'].split()[0]}" 
                    g_url = f"https://maps.googleapis.com/maps/api/place/findplacefromtext/json?input={urllib.parse.quote(search_query)}&inputtype=textquery&fields=place_id,rating,user_ratings_total,photos,opening_hours&locationbias=point:{p.get('y')},{p.get('x')}&key={google_api_key}"
                    import requests
                    g_resp = requests.get(g_url, timeout=2.0).json()
                    
                    if g_resp.get('status') == 'OK' and g_resp.get('candidates'):
                        cand = g_resp['candidates'][0]
                        rating = cand.get('rating')
                        total_ratings = cand.get('user_ratings_total', 0)
                        
                        item['total_ratings'] = total_ratings
                        item['place_id'] = cand.get('place_id')
                        
                        if 'opening_hours' in cand:
                            item['is_open'] = cand['opening_hours'].get('open_now')
                            
                        if 'photos' in cand and cand['photos']:
                            photo_ref = cand['photos'][0].get('photo_reference')
                            item['photo_url'] = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photo_reference={photo_ref}&key={google_api_key}"
                        
                        if rating and total_ratings >= 10:
                            item['rating'] = str(rating)
                            item['trust_score'] = int(float(rating) * total_ratings)
                        else:
                            item['rating'] = "평가 부족"
                            item['trust_score'] = 0
                except Exception:
                    pass
            
            return item

        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            scraped_places = list(executor.map(scrape_place, places[:50]))
            
        results = sorted(scraped_places, key=lambda k: k.get('trust_score', 0), reverse=True)
        
        return jsonify({
            "success": True, 
            "data": results, 
            "center": None
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": f"검색 중 오류 발생: {str(e)}"})


