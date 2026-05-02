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


def haversine(lat1, lon1, lat2, lon2):
    import math
    R = 6371000
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def get_search_points(lat, lng, radius_m):
    import math
    lat = float(lat)
    lng = float(lng)
    radius_m = int(radius_m)
    points = [{"lat": lat, "lng": lng}]
    if radius_m <= 2000:
        return points
    offset_m = radius_m * 0.6
    lat_offset = offset_m / 111320.0
    lng_offset = offset_m / (111320.0 * math.cos(math.radians(lat)))
    points.append({"lat": lat + lat_offset, "lng": lng})
    points.append({"lat": lat - lat_offset, "lng": lng})
    points.append({"lat": lat, "lng": lng + lng_offset})
    points.append({"lat": lat, "lng": lng - lng_offset})
    if radius_m >= 10000:
        points.append({"lat": lat + lat_offset*0.7, "lng": lng + lng_offset*0.7})
        points.append({"lat": lat - lat_offset*0.7, "lng": lng - lng_offset*0.7})
        points.append({"lat": lat + lat_offset*0.7, "lng": lng - lng_offset*0.7})
        points.append({"lat": lat - lat_offset*0.7, "lng": lng + lng_offset*0.7})
    return points


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

def _call_groq(api_key, prompt, system_role="You are a helpful assistant.", model="llama3-8b-8192", temperature=0.7):
    import requests
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    messages = []
    if system_role:
        messages.append({"role": "system", "content": system_role})
    messages.append({"role": "user", "content": prompt})
    
    data = {
        "model": model,
        "messages": messages,
        "temperature": temperature
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        resp.raise_for_status()
        return True, resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return False, str(e)

def _call_groq_stream(api_key, prompt, system_role="You are a helpful assistant.", model="llama3-8b-8192", temperature=0.7):
    import requests, json
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    messages = []
    if system_role: messages.append({"role": "system", "content": system_role})
    messages.append({"role": "user", "content": prompt})
    data = {"model": model, "messages": messages, "temperature": temperature, "stream": True}
    
    try:
        with requests.post(url, headers=headers, json=data, stream=True, timeout=10) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith("data: "):
                        data_str = line_str[6:]
                        if data_str.strip() == "[DONE]":
                            yield "data: [DONE]\n\n"
                            break
                        try:
                            chunk = json.loads(data_str)
                            content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if content:
                                yield f"data: {json.dumps({'text': content})}\n\n"
                        except:
                            pass
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

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
        
        # 2. 다중 키워드 분산 검색 (거리별로 다양한 결과를 얻기 위함)
        places = []
        seen_ids = set()
        
        # 반경에 따라 키워드 수 조정
        keywords = ["맛집", "고기집", "횟집", "레스토랑", "파스타", "국밥"]
        if radius >= 5000:
            keywords.extend(["피자", "치킨", "한정식", "브런치", "짬뽕", "스테이크", "오마카세", "야식"])
            

        search_points = [{"lat": float(y), "lng": float(x)}]
        
        import concurrent.futures
        def fetch_kw(pt, kw):
            try:
                import urllib.parse, requests
                r_val = int(radius)//2 if int(radius) > 3000 else radius
                docs = []
                for p in [1, 2]:
                    k_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(kw)}&x={pt['lng']}&y={pt['lat']}&radius={r_val}&page={p}"
                    resp = requests.get(k_url, headers=headers, timeout=3).json()
                    docs.extend(resp.get('documents', []))
                    if resp.get('meta', {}).get('is_end', True): break
                return docs
            except:
                return []
                
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            for pt in search_points:
                for kw in keywords:
                    futures.append(executor.submit(fetch_kw, pt, kw))
                    
        
        
        for future in concurrent.futures.as_completed(futures):
            docs = future.result()
            for d in docs:
                p_name = d.get('place_name', '')
                try:
                    d_lat = float(d.get('y', 0))
                    d_lng = float(d.get('x', 0))
                    actual_dist = haversine(float(y), float(x), d_lat, d_lng)
                    d['distance'] = str(int(actual_dist))
                    
                    if actual_dist <= int(radius) and d['id'] not in seen_ids and True:
                        places.append(d)
                        seen_ids.add(d['id'])
                except Exception as e:
                    pass

                
        if not places:
            return jsonify({"success": False, "error": "해당 반경 내에 검색된 음식점이 없습니다."})
            
        # 거리가 먼 결과도 포함되도록 거리순으로 정렬 후 균등 샘플링 (최대 50개)
        places.sort(key=lambda p: int(p.get('distance', 0)))
        
        limit = 80
        if radius >= 20000: limit = 200
        elif radius >= 10000: limit = 150
        elif radius >= 5000: limit = 120
        
        if len(places) > limit:
            places = places[:limit]
            
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
        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
            scraped_places = list(executor.map(scrape_place, places[:limit])) # 최대 30개에서 50개로 확장
            
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
    
    import requests
    addr_url = f"https://dapi.kakao.com/v2/local/geo/coord2address.json?x={lng}&y={lat}"
    try:
        resp = requests.get(addr_url, headers={"Authorization": f"KakaoAK {api_key}"}).json()
        docs = resp.get("documents", [])
        if docs:
            d = docs[0]
            if d.get("road_address") and d["road_address"].get("address_name"):
                return jsonify({"success": True, "address": d["road_address"]["address_name"]})
            elif d.get("address") and d["address"].get("address_name"):
                return jsonify({"success": True, "address": d["address"]["address_name"]})
                
        region_url = f"https://dapi.kakao.com/v2/local/geo/coord2regioncode.json?x={lng}&y={lat}"
        resp2 = requests.get(region_url, headers={"Authorization": f"KakaoAK {api_key}"}).json()
        docs2 = resp2.get("documents", [])
        if docs2:
            for d in docs2:
                if d.get("region_type") == "B":
                    return jsonify({"success": True, "address": d.get("address_name")})
            return jsonify({"success": True, "address": docs2[0].get("address_name")})
            
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
            
        from ai_cache import get_cached_summary, save_cached_summary
        cached = get_cached_summary(place_id, purpose)
        if cached:
            return jsonify({"success": True, "summary": cached, "cached": True})
            
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
        
        response = model.generate_content(prompt, request_options={'timeout': 30})
        
        res_text = response.text.strip()
        if "```json" in res_text:
             res_text = res_text.split("```json")[1].split("```")[0].strip()
        elif "```" in res_text:
             res_text = res_text.split("```")[1].strip()
             
        try:
            parsed_data = json.loads(res_text)
            save_cached_summary(place_id, purpose, parsed_data)
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
        
        response = model.generate_content(prompt, request_options={'timeout': 30})
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

@scanner_bp.route("/api/restaurant/chat/stream", methods=["POST"])
def restaurant_chat_stream():
    from flask import Response
    data = request.json or {}
    place_id = data.get("place_id")
    question = data.get("question")
    import os, requests
    google_api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    
    if not place_id or not google_api_key or not question:
        return Response("data: {\"error\": \"요청 정보 오류\"}\n\n", mimetype="text/event-stream")
        
    det_url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=reviews&language=ko&key={google_api_key}"
    resp = requests.get(det_url).json()
    reviews = resp.get("result", {}).get("reviews", [])
    
    if not reviews:
        return Response("data: {\"text\": \"아직 리뷰가 등록되지 않아 답변할 수 없습니다.\"}\n\ndata: [DONE]\n\n", mimetype="text/event-stream")
        
    review_texts = [r.get("text") for r in reviews if r.get("text")]
    combined_text = "\n".join(review_texts[:5])
    
    if not combined_text.strip():
        return Response("data: {\"text\": \"텍스트 리뷰가 없어 구체적인 답변을 드릴 수 없습니다.\"}\n\ndata: [DONE]\n\n", mimetype="text/event-stream")
        
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        return Response("data: {\"error\": \"Groq API 키 누락\"}\n\n", mimetype="text/event-stream")
        
    prompt = f"다음은 이 가게의 최근 방문자 리뷰입니다:\n{combined_text}\n\n사용자의 질문: {question}\n\n위 리뷰 내용을 바탕으로 질문에 친절하게 답변해주세요. 정보가 없으면 '알 수 없다'고 하세요."
    sys_role = "당신은 식당/장소 리뷰 분석 AI입니다. 한국어로 자연스럽게 대답하세요."
    
    return Response(_call_groq_stream(groq_api_key, prompt, system_role=sys_role), mimetype="text/event-stream")

@scanner_bp.route('/bakery')
def bakery():
    import os
    return render_template('bakery.html', google_maps_api_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))


@scanner_bp.route('/api/bakery/search', methods=['POST'])
def bakery_search():
    data = request.json
    address = data.get('address', '').strip()
    radius = int(data.get('radius', 3000))
    lat = data.get('lat')
    lng = data.get('lng')
    import os, urllib.parse, requests
    from flask import jsonify
    
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "서비스 설정 오류: 카카오 REST API 키가 환경 변수에 등록되지 않았습니다."})
        
    if not address and not (lat and lng):
        return jsonify({"success": False, "error": "지역명을 입력하거나 현재 위치를 허용해주세요."})
        
    headers = {"Authorization": f"KakaoAK {api_key}"}
    
    try:
        if lat and lng:
            x = str(lng)
            y = str(lat)
        else:
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

        places = []
        seen_ids = set()
        
        keywords = ["유명한 빵집", "베이커리 카페", "디저트", "마카롱", "케이크", "식빵", "소금빵"]
        if int(radius) >= 5000:
            keywords.extend(["타르트", "스콘", "크로플", "도넛", "수제버거", "샌드위치"])
            

        search_points = [{"lat": float(y), "lng": float(x)}]
        
        import concurrent.futures
        def fetch_kw(pt, kw):
            try:
                import urllib.parse, requests
                r_val = int(radius)//2 if int(radius) > 3000 else radius
                docs = []
                for p in [1, 2]:
                    k_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(kw)}&x={pt['lng']}&y={pt['lat']}&radius={r_val}&page={p}"
                    resp = requests.get(k_url, headers=headers, timeout=3).json()
                    docs.extend(resp.get('documents', []))
                    if resp.get('meta', {}).get('is_end', True): break
                return docs
            except:
                return []
                
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            for pt in search_points:
                for kw in keywords:
                    futures.append(executor.submit(fetch_kw, pt, kw))
                    
        ignore_keywords = ['파리바게', '뚜레쥬', '뚜레주', '파리크라상', '던킨', '배스킨', '베스킨', '크리스피크림']
        
        for future in concurrent.futures.as_completed(futures):
            docs = future.result()
            for d in docs:
                p_name = d.get('place_name', '')
                try:
                    d_lat = float(d.get('y', 0))
                    d_lng = float(d.get('x', 0))
                    actual_dist = haversine(float(y), float(x), d_lat, d_lng)
                    d['distance'] = str(int(actual_dist))
                    
                    if actual_dist <= int(radius) and d['id'] not in seen_ids and not any(k in p_name for k in ignore_keywords):
                        places.append(d)
                        seen_ids.add(d['id'])
                except Exception as e:
                    pass

                
        if not places:
            return jsonify({"success": False, "error": f"검색된 빵집/디저트 결과가 없습니다."})
            
        places.sort(key=lambda p: int(p.get('distance', 0)))
        
        limit = 80
        if radius >= 20000: limit = 200
        elif radius >= 10000: limit = 150
        elif radius >= 5000: limit = 120
        
        if len(places) > limit:
            places = places[:limit]
            
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
            scraped_places = list(executor.map(scrape_place, places[:limit]))
            
        results = sorted(scraped_places, key=lambda k: k.get('trust_score', 0), reverse=True)
        
        return jsonify({
            "success": True, 
            "data": results, 
            "center": {"x": x, "y": y}
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
    radius = int(data.get('radius', 3000))
    lat = data.get('lat')
    lng = data.get('lng')
    import os, urllib.parse, requests
    from flask import jsonify
    
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "서비스 설정 오류: 카카오 REST API 키가 환경 변수에 등록되지 않았습니다."})
        
    if not address and not (lat and lng):
        return jsonify({"success": False, "error": "지역명을 입력하거나 현재 위치를 허용해주세요."})
        
    headers = {"Authorization": f"KakaoAK {api_key}"}
    
    try:
        if lat and lng:
            x = str(lng)
            y = str(lat)
        else:
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

        places = []
        seen_ids = set()
        
        keywords = ["분위기 좋은 카페", "디저트 카페", "로스터리", "에스프레소 바", "대형 카페", "감성 카페"]
        if int(radius) >= 5000:
            keywords.extend(["브런치 카페", "테라스 카페", "루프탑 카페", "뷰맛집 카페", "핸드드립"] )
            

        search_points = [{"lat": float(y), "lng": float(x)}]
        
        import concurrent.futures
        def fetch_kw(pt, kw):
            try:
                import urllib.parse, requests
                r_val = int(radius)//2 if int(radius) > 3000 else radius
                docs = []
                for p in [1, 2]:
                    k_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(kw)}&x={pt['lng']}&y={pt['lat']}&radius={r_val}&page={p}"
                    resp = requests.get(k_url, headers=headers, timeout=3).json()
                    docs.extend(resp.get('documents', []))
                    if resp.get('meta', {}).get('is_end', True): break
                return docs
            except:
                return []
                
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            for pt in search_points:
                for kw in keywords:
                    futures.append(executor.submit(fetch_kw, pt, kw))
                    
        ignore_keywords = ['스타벅스', '투썸', '이디야', '메가커피', '메가MGC', '컴포즈', '빽다방', '할리스', '파스쿠찌', '엔제리너스', '탐앤탐스', '폴바셋', '커피빈']
        
        for future in concurrent.futures.as_completed(futures):
            docs = future.result()
            for d in docs:
                p_name = d.get('place_name', '')
                try:
                    d_lat = float(d.get('y', 0))
                    d_lng = float(d.get('x', 0))
                    actual_dist = haversine(float(y), float(x), d_lat, d_lng)
                    d['distance'] = str(int(actual_dist))
                    
                    if actual_dist <= int(radius) and d['id'] not in seen_ids and not any(k in p_name for k in ignore_keywords):
                        places.append(d)
                        seen_ids.add(d['id'])
                except Exception as e:
                    pass

                
        if not places:
            return jsonify({"success": False, "error": f"검색된 카페 결과가 없습니다."})
            
        places.sort(key=lambda p: int(p.get('distance', 0)))
        
        limit = 80
        if radius >= 20000: limit = 200
        elif radius >= 10000: limit = 150
        elif radius >= 5000: limit = 120
        
        if len(places) > limit:
            places = places[:limit]
            
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
            scraped_places = list(executor.map(scrape_place, places[:limit]))
            
        results = sorted(scraped_places, key=lambda k: k.get('trust_score', 0), reverse=True)
        
        return jsonify({
            "success": True, 
            "data": results, 
            "center": {"x": x, "y": y}
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
    radius = int(data.get('radius', 3000))
    lat = data.get('lat')
    lng = data.get('lng')
    import os, urllib.parse, requests
    from flask import jsonify
    
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "서비스 설정 오류: 카카오 REST API 키가 환경 변수에 등록되지 않았습니다."})
        
    if not address and not (lat and lng):
        return jsonify({"success": False, "error": "지역명 또는 주소를 입력하거나 현재 위치를 허용해주세요."})
        
    headers = {"Authorization": f"KakaoAK {api_key}"}
    
    try:
        if lat and lng:
            x = str(lng)
            y = str(lat)
        else:
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
        
        places = []
        seen_ids = set()
        
        keywords = ["치과", "피부과", "내과", "이비인후과", "안과", "정형외과", "소아과", "한의원", "재활의학과", "통증의학과"]
        if int(radius) >= 5000:
            keywords.extend(["성형외과", "산부인과", "비뇨기과", "신경외과", "건강검진", "클리닉"])
            

        search_points = [{"lat": float(y), "lng": float(x)}]
        
        import concurrent.futures
        def fetch_kw(pt, kw):
            try:
                import urllib.parse, requests
                r_val = int(radius)//2 if int(radius) > 3000 else radius
                docs = []
                for p in [1, 2]:
                    k_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(kw)}&x={pt['lng']}&y={pt['lat']}&radius={r_val}&page={p}"
                    resp = requests.get(k_url, headers=headers, timeout=3).json()
                    docs.extend(resp.get('documents', []))
                    if resp.get('meta', {}).get('is_end', True): break
                return docs
            except:
                return []
                
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            for pt in search_points:
                for kw in keywords:
                    futures.append(executor.submit(fetch_kw, pt, kw))
                    
        ignore_keywords = ["요양", "동물", "수의", "대학병원", "대학교병원", "의료원", "보건소"]
        
        for future in concurrent.futures.as_completed(futures):
            docs = future.result()
            for d in docs:
                p_name = d.get('place_name', '')
                try:
                    d_lat = float(d.get('y', 0))
                    d_lng = float(d.get('x', 0))
                    actual_dist = haversine(float(y), float(x), d_lat, d_lng)
                    d['distance'] = str(int(actual_dist))
                    
                    if actual_dist <= int(radius) and d['id'] not in seen_ids and not any(k in p_name for k in ignore_keywords):
                        places.append(d)
                        seen_ids.add(d['id'])
                except Exception as e:
                    pass

                
        if not places:
            return jsonify({"success": False, "error": "해당 반경 내에 검색된 병원/클리닉이 없습니다."})
            
        places.sort(key=lambda p: int(p.get('distance', 0)))
        
        limit = 80
        if radius >= 20000: limit = 200
        elif radius >= 10000: limit = 150
        elif radius >= 5000: limit = 120
        
        if len(places) > limit:
            places = places[:limit]
            
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
            scraped_places = list(executor.map(scrape_place, places[:limit]))
            
        results = sorted(scraped_places, key=lambda k: k.get('trust_score', 0), reverse=True)
        
        return jsonify({
            "success": True, 
            "data": results, 
            "center": {"x": x, "y": y}
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": f"검색 중 오류 발생: {str(e)}"})




@scanner_bp.route('/course')
def course():
    import os
    return render_template('course.html', google_maps_api_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))

@scanner_bp.route('/api/course/generate', methods=['POST'])
def course_generate():
    data = request.json
    address = data.get('address', '').strip()
    purpose = data.get('purpose', '로맨틱 데이트')
    
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "카카오 API 키 누락"})
        
    headers = {"Authorization": f"KakaoAK {api_key}"}
    import urllib.parse, requests
    
    # 주소 -> 좌표
    geo_url = f"https://dapi.kakao.com/v2/local/search/address.json?query={urllib.parse.quote(address)}"
    geo_resp = requests.get(geo_url, headers=headers).json()
    if not geo_resp.get('documents'):
        geo_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(address)}"
        geo_resp = requests.get(geo_url, headers=headers).json()
    if not geo_resp.get('documents'):
        return jsonify({"success": False, "error": "주소를 찾을 수 없습니다."})
        
    x = geo_resp['documents'][0]['x']
    y = geo_resp['documents'][0]['y']
    
    # 카카오 카테고리 검색: FD6(음식점), CE7(카페), CT1(문화시설), AT4(관광명소), PK6(공원)
    places_pool = []
    
    for cat in ['FD6', 'CE7', 'CT1', 'AT4', 'PK6']:
        url = f"https://dapi.kakao.com/v2/local/search/category.json?category_group_code={cat}&x={x}&y={y}&radius=3000&sort=accuracy"
        resp = requests.get(url, headers=headers).json()
        docs = resp.get('documents', [])
        # 카테고리별 상위 5개 추출
        for d in docs[:5]:
            places_pool.append({
                "name": d['place_name'],
                "category": d['category_group_name'] or d['category_name'],
                "lat": d['y'],
                "lng": d['x'],
                "address": d.get('road_address_name') or d.get('address_name')
            })
            
    # Gemini AI에게 조합 요청
    import json
    groq_api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GROQ_API_KEY')
    if not groq_api_key:
        return jsonify({"success": False, "error": "AI API 키 누락"})
        
    prompt = f"""
다음 장소 후보들을 바탕으로 '{address}' 주변의 '{purpose}' 목적에 맞는 최고의 원데이 코스 3곳(예: 식사 -> 카페 -> 놀거리 등)을 기획해줘.
장소 후보:
{json.dumps(places_pool, ensure_ascii=False, indent=2)}

출력은 반드시 다음 JSON 형식으로만 해줘. 마크다운이나 다른 설명은 절대 넣지마.
{{
  "summary": "이 코스를 기획한 전체적인 이유와 분위기 요약 (2-3문장)",
  "course": [
    {{
      "name": "장소명",
      "category": "카테고리명",
      "lat": "위도",
      "lng": "경도",
      "reason": "이 장소를 코스에 넣은 이유 (1문장)"
    }},
    ... 3개 작성 ...
  ]
}}
"""
    try:
        if os.environ.get('GEMINI_API_KEY'):
            import google.generativeai as genai
            genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(prompt)
            raw_text = response.text
        else:
            # Fallback to groq
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5,
                "response_format": {"type": "json_object"}
            }
            resp = requests.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.environ.get('GROQ_API_KEY')}", "Content-Type": "application/json"},
                json=payload
            ).json()
            raw_text = resp['choices'][0]['message']['content']
            
        # Extract JSON robustly
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()
        start_idx = raw_text.find("{")
        end_idx = raw_text.rfind("}")
        if start_idx != -1 and end_idx != -1:
            raw_text = raw_text[start_idx:end_idx+1]
        result_json = json.loads(raw_text)
        
        return jsonify({
            "success": True,
            "course": result_json.get("course", []),
            "summary": result_json.get("summary", "")
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"AI 코스 기획 중 오류 발생: {str(e)}"})


@scanner_bp.route('/estate')
def estate():
    import os
    return render_template('estate.html', google_maps_api_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))

@scanner_bp.route('/api/estate/analyze', methods=['POST'])
def estate_analyze():
    data = request.json
    address = data.get('address', '').strip()
    radius = data.get('radius', '1000')
    
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "카카오 API 키 누락"})
        
    headers = {"Authorization": f"KakaoAK {api_key}"}
    import urllib.parse, requests
    
    geo_url = f"https://dapi.kakao.com/v2/local/search/address.json?query={urllib.parse.quote(address)}"
    geo_resp = requests.get(geo_url, headers=headers).json()
    if not geo_resp.get('documents'):
        geo_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(address)}"
        geo_resp = requests.get(geo_url, headers=headers).json()
    if not geo_resp.get('documents'):
        return jsonify({"success": False, "error": "주소를 찾을 수 없습니다."})
        
    x = geo_resp['documents'][0]['x']
    y = geo_resp['documents'][0]['y']
    
    categories = ['MT1', 'CS2', 'PS3', 'SC4', 'SW8', 'HP8', 'PM9', 'PK6', 'CE7']
    counts = {}
    top_places = {}
    places_dict = {}
    import concurrent.futures
    
    def fetch_data(cat):
        url = f"https://dapi.kakao.com/v2/local/search/category.json?category_group_code={cat}&x={x}&y={y}&radius={radius}&sort=distance"
        try:
            resp = requests.get(url, headers=headers).json()
            total_count = resp['meta']['total_count']
            top_place = None
            docs_list = []
            if total_count > 0 and resp.get('documents'):
                docs_list = [{"name": d['place_name'], "distance": d['distance'], "url": d.get('place_url', '#')} for d in resp['documents'][:15]]
                doc = resp['documents'][0]
                top_place = {
                    "name": doc['place_name'],
                    "distance": doc['distance']
                }
            return cat, total_count, top_place, docs_list
        except Exception as e:
            print(f"Error fetching {cat}: {e}")
            return cat, 0, None, []
            
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for cat, count, top_place, docs_list in executor.map(fetch_data, categories):
            counts[cat] = count
            places_dict[cat] = docs_list
            if top_place:
                top_places[cat] = top_place
            
    # 점수 계산 (단순 로직)
    transport = min(100, counts.get('SW8', 0) * 30 + 10)
    education = min(100, (counts.get('SC4', 0) + counts.get('PS3', 0)) * 15)
    shopping = min(100, counts.get('MT1', 0) * 40 + counts.get('CE7', 0) * 5)
    nature = min(100, counts.get('PK6', 0) * 20 + 20)
    medical = min(100, (counts.get('HP8', 0) + counts.get('PM9', 0)) * 5)
    convenience = min(100, counts.get('CS2', 0) * 5)
    
    scores = {
        "transport": transport,
        "education": education,
        "shopping": shopping,
        "nature": nature,
        "medical": medical,
        "convenience": convenience
    }
    total_score = int((transport + education + shopping + nature + medical + convenience) / 6)
    
    # Gemini AI 요약
    import json
    prompt = f"""
'{address}' 주변 반경 {radius}m 내의 인프라 데이터입니다.
- 대형마트: {counts.get('MT1')}개 (가장 가까운 곳: {top_places.get('MT1', {}).get('name', '없음')} - {top_places.get('MT1', {}).get('distance', '')}m)
- 지하철역: {counts.get('SW8')}개 (가장 가까운 곳: {top_places.get('SW8', {}).get('name', '없음')} - {top_places.get('SW8', {}).get('distance', '')}m)
- 학교: {counts.get('SC4')}개 (가장 가까운 곳: {top_places.get('SC4', {}).get('name', '없음')} - {top_places.get('SC4', {}).get('distance', '')}m)
- 공원: {counts.get('PK6')}개 (가장 가까운 곳: {top_places.get('PK6', {}).get('name', '없음')} - {top_places.get('PK6', {}).get('distance', '')}m)
- 병원: {counts.get('HP8')}개 (가장 가까운 곳: {top_places.get('HP8', {}).get('name', '없음')} - {top_places.get('HP8', {}).get('distance', '')}m)
- 편의점: {counts.get('CS2')}개, 카페: {counts.get('CE7')}개

위 랜드마크(이름과 거리)를 바탕으로 이곳에 실제로 거주한다면 어떤 느낌일지, 장단점은 무엇일지 "부동산 전문가이자 친근한 이웃"의 말투로 분석 보고서를 작성해주세요.
반드시 제공된 실제 랜드마크 이름(예: OO역, OO초등학교, OO공원 등)을 구체적으로 언급하며 브리핑해주세요.
(단락을 나누어 보기 좋게 작성하고 핵심 키워드는 볼드 처리해주세요. 400자 이내)
"""
    try:
        summary_text = "AI 분석을 불러오는 중 오류가 발생했습니다."
        if os.environ.get('GEMINI_API_KEY'):
            import google.generativeai as genai
            genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(prompt)
            summary_text = response.text
        else:
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5
            }
            resp = requests.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.environ.get('GROQ_API_KEY')}", "Content-Type": "application/json"},
                json=payload
            ).json()
            summary_text = resp['choices'][0]['message']['content']
    except:
        pass
        
    return jsonify({
        "success": True,
        "counts": counts,
        "top_places": top_places,
        "places_dict": places_dict,
        "scores": scores,
        "total_score": total_score,
        "summary": summary_text,
        "center": {"lat": y, "lng": x},
        "radius": radius
    })

@scanner_bp.route('/lotto_scanner')
def lotto_scanner():
    import os
    return render_template('lotto.html', google_maps_api_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))

@scanner_bp.route('/api/lotto/search', methods=['POST'])
def lotto_search():
    data = request.json
    address = data.get('address', '').strip()
    radius = int(data.get('radius', 3000))
    lat = data.get('lat')
    lng = data.get('lng')
    import os, urllib.parse, requests
    from flask import jsonify
    
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "서비스 설정 오류: 카카오 REST API 키가 환경 변수에 등록되지 않았습니다."})
        
    if not address and not (lat and lng):
        return jsonify({"success": False, "error": "지역명을 입력하거나 현재 위치를 허용해주세요."})
        
    headers = {"Authorization": f"KakaoAK {api_key}"}
    
    try:
        if lat and lng:
            x = str(lng)
            y = str(lat)
        else:
            geo_url = f"https://dapi.kakao.com/v2/local/search/address.json?query={urllib.parse.quote(address)}"
            geo_resp = requests.get(geo_url, headers=headers).json()
            if not geo_resp.get('documents'):
                geo_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(address)}"
                geo_resp = requests.get(geo_url, headers=headers).json()
            if not geo_resp.get('documents'):
                return jsonify({"success": False, "error": "해당 주소나 지역을 찾을 수 없습니다."})
            x = geo_resp['documents'][0]['x']
            y = geo_resp['documents'][0]['y']

        places = []
        seen_ids = set()
        
        keywords = ["로또명당", "복권방", "스피또"]
        search_points = [{"lat": float(y), "lng": float(x)}]
        
        import concurrent.futures
        def fetch_kw(pt, kw):
            try:
                import urllib.parse, requests
                r_val = int(radius)//2 if int(radius) > 3000 else radius
                docs = []
                for p in [1, 2]:
                    k_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(kw)}&x={pt['lng']}&y={pt['lat']}&radius={r_val}&page={p}"
                    resp = requests.get(k_url, headers=headers, timeout=3).json()
                    docs.extend(resp.get('documents', []))
                    if resp.get('meta', {}).get('is_end', True): break
                return docs
            except:
                return []
                
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            for pt in search_points:
                for kw in keywords:
                    futures.append(executor.submit(fetch_kw, pt, kw))
                    
        for future in concurrent.futures.as_completed(futures):
            docs = future.result()
            for d in docs:
                p_name = d.get('place_name', '')
                try:
                    d_lat = float(d.get('y', 0))
                    d_lng = float(d.get('x', 0))
                    actual_dist = haversine(float(y), float(x), d_lat, d_lng)
                    d['distance'] = str(int(actual_dist))
                    
                    if actual_dist <= int(radius) and d['id'] not in seen_ids:
                        places.append(d)
                        seen_ids.add(d['id'])
                except Exception as e:
                    pass

        if not places:
            return jsonify({"success": False, "error": f"검색된 복권방 결과가 없습니다."})
            
        places.sort(key=lambda p: int(p.get('distance', 0)))
        
        limit = 80
        if radius >= 20000: limit = 200
        elif radius >= 10000: limit = 150
        elif radius >= 5000: limit = 120
        
        if len(places) > limit:
            places = places[:limit]
            
        results = []
        for p in places:
            pid = p.get('id')
            p_name = p.get('place_name')
            p_url = p.get('place_url')
            full_cat = p.get('category_name', '')
            dist_str = p.get('distance', '0')
            dist = int(dist_str) if dist_str else 0
            
            cat_simplified = "기타"
            if "명당" in p_name: cat_simplified = "로또명당"
            elif "스피또" in p_name or "연금" in p_name: cat_simplified = "스피또/연금"
            elif "복권" in p_name or "로또" in p_name: cat_simplified = "일반복권방"
            
            # 카카오 API는 rating이 없으므로 N/A 처리, trust_score는 0
            # 명당 단어가 포함되면 trust_score에 가산점
            trust = 0
            if "명당" in p_name: trust += 500
            
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
                'place_id': pid, # Kakao ID instead of Google place_id
                'photo_url': None,
                'is_open': None,
                'trust_score': trust
            }
            results.append(item)
            
        # --- 당첨 이력 일괄 스캔 로직 (병렬 처리) ---
        import re
        def fetch_history(item):
            place_name = item['name']
            address = item['address'] or ""
            region_keyword = ""
            parts = address.split()
            if len(parts) >= 2:
                region_keyword = parts[0] + " " + parts[1] + " "
            
            query_str = f"{region_keyword}{place_name} 로또 1등 당첨"
            blog_texts = ""
            if api_key:
                try:
                    url = f"https://dapi.kakao.com/v2/search/blog?query={urllib.parse.quote(query_str)}&size=5"
                    resp = requests.get(url, headers=headers, timeout=2).json()
                    for doc in resp.get('documents', []):
                        title = doc.get('title', '').replace('<b>', '').replace('</b>', '')
                        desc = doc.get('contents', '').replace('<b>', '').replace('</b>', '')
                        blog_texts += title + " " + desc + "\n"
                except:
                    pass
            
            first_matches = [int(m) for m in re.findall(r'1등\s*(\d+)\s*[번회]', blog_texts)]
            second_matches = [int(m) for m in re.findall(r'2등\s*(\d+)\s*[번회]', blog_texts)]
            
            first_count = max(first_matches) if first_matches else 0
            second_count = max(second_matches) if second_matches else 0
            
            item['first_count'] = first_count
            item['second_count'] = second_count
            
            target_score = 50
            vibe = "빠른 당첨 이력 스캔 완료"
            hashtags = ["로또명당", "대박기원"]
            
            if first_count > 0:
                summary_text = f"🎉 <b>1등 당첨: {first_count}번 이상 추정</b><br>"
                target_score = 95
                hashtags.append("1등배출점")
            else:
                summary_text = f"1등 당첨: 명확한 이력 없음<br>"
                
            if second_count > 0:
                summary_text += f"✨ <b>2등 당첨: {second_count}번 이상 추정</b><br>"
            else:
                summary_text += f"2등 당첨: 명확한 이력 없음<br>"
                
            if first_count == 0 and second_count == 0:
                summary_text += "<br>※ 온라인 리뷰상 정확한 당첨 횟수는 추출되지 않았습니다."
            else:
                summary_text += "<br>※ 이 곳은 실제 사람들의 리뷰에서도 당첨 인증이 발견되는 명당입니다!"
                
            item['ai_summary'] = {
                "target_score": target_score,
                "recent_vibe": vibe,
                "summary": summary_text,
                "hashtags": hashtags
            }
            return item

        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
            results = list(executor.map(fetch_history, results))
            
        # 기본 정렬: 1등 당첨 많은 순 우선, 그 다음 trust_score
        results.sort(key=lambda x: (x.get('first_count', 0), x['trust_score']), reverse=True)
        # ----------------------------------------------
            
        return jsonify({
            "success": True, 
            "data": results, 
            "center": {"x": x, "y": y}
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@scanner_bp.route('/api/lotto/history', methods=['POST'])
def lotto_history():
    data = request.json
    place_name = data.get('place_name')
    address = data.get('address', '')
    if not place_name:
        return jsonify({"success": False, "error": "가게 이름이 없습니다."})
        
    import os, urllib.parse, requests, re
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    
    # 주소의 앞부분(시/구/동)을 추출하여 검색어에 포함 (정확도 향상)
    region_keyword = ""
    if address:
        parts = address.split()
        if len(parts) >= 2:
            region_keyword = parts[0] + " " + parts[1] + " "
    
    query_str = f"{region_keyword}{place_name} 로또 1등 당첨"
    
    blog_texts = ""
    if api_key:
        try:
            # 카카오 블로그 검색 활용 (속도 향상을 위해 size=5로 축소 및 timeout=2 설정)
            url = f"https://dapi.kakao.com/v2/search/blog?query={urllib.parse.quote(query_str)}&size=5"
            headers = {"Authorization": f"KakaoAK {api_key}"}
            resp = requests.get(url, headers=headers, timeout=2).json()
            for item in resp.get('documents', []):
                # HTML 태그 제거
                title = item.get('title', '').replace('<b>', '').replace('</b>', '')
                desc = item.get('contents', '').replace('<b>', '').replace('</b>', '')
                blog_texts += title + " " + desc + "\n"
        except:
            pass

    # 정규식을 통한 즉각적인 텍스트 추출 (AI 대신)
    first_matches = [int(m) for m in re.findall(r'1등\s*(\d+)\s*[번회]', blog_texts)]
    second_matches = [int(m) for m in re.findall(r'2등\s*(\d+)\s*[번회]', blog_texts)]
    
    first_count = max(first_matches) if first_matches else 0
    second_count = max(second_matches) if second_matches else 0
    
    target_score = 50
    vibe = "빠른 당첨 이력 스캔 완료"
    hashtags = ["로또명당", "대박기원"]
    
    if first_count > 0:
        summary_text = f"🎉 <b>1등 당첨: {first_count}번 이상 추정</b><br>"
        target_score = 95
        hashtags.append("1등배출점")
    else:
        summary_text = f"1등 당첨: 명확한 이력 없음<br>"
        
    if second_count > 0:
        summary_text += f"✨ <b>2등 당첨: {second_count}번 이상 추정</b><br>"
    else:
        summary_text += f"2등 당첨: 명확한 이력 없음<br>"
        
    if first_count == 0 and second_count == 0:
        summary_text += "<br>※ 온라인 리뷰상 정확한 당첨 횟수는 추출되지 않았습니다."
    else:
        summary_text += "<br>※ 이 곳은 실제 사람들의 리뷰에서도 당첨 인증이 발견되는 명당입니다!"

    return jsonify({
        "success": True,
        "summary": {
            "target_score": target_score,
            "recent_vibe": vibe,
            "summary": summary_text,
            "hashtags": hashtags
        }
    })
