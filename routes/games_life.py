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

games_life_bp = Blueprint('games_life', __name__)

GROQ_MODEL_CACHE = None

def get_best_groq_model(api_key):
    global GROQ_MODEL_CACHE
    if GROQ_MODEL_CACHE:
        return GROQ_MODEL_CACHE
    
    import requests
    try:
        url = "https://api.groq.com/openai/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            available_models = [m['id'] for m in data.get('data', [])]
            for target in ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "llama-3.1-8b-instant"]:
                if target in available_models:
                    GROQ_MODEL_CACHE = target
                    return target
            
            # Fallback to any llama model
            llama_models = [m for m in available_models if 'llama' in m.lower()]
            if llama_models:
                GROQ_MODEL_CACHE = llama_models[0]
                return GROQ_MODEL_CACHE
    except Exception:
        pass
        
    # Ultimate hardcoded fallback
    return "llama-3.3-70b-versatile"

def _call_groq_chat(api_key, messages, temperature=0.7):
    import requests
    model_name = get_best_groq_model(api_key)
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature
    }
    
    try:
        resp = requests.post(url, headers=headers, json=payload)
        resp_data = resp.json()
        
        if 'error' in resp_data:
            err_msg = resp_data['error'].get('message', '알 수 없는 오류')
            return False, f"Groq 통신 실패: {err_msg}"
            
        text = resp_data['choices'][0]['message']['content'].strip()
        return True, text
    except Exception as e:
        return False, f"Groq 시스템 오류 발생: {str(e)}"

def _call_gemini_chat(api_key, messages, temperature=0.7):
    import google.generativeai as genai
    try:
        genai.configure(api_key=api_key)
        
        system_instruction = ""
        gemini_messages = []
        for msg in messages:
            role = msg['role']
            content = msg['content']
            if role == 'system':
                system_instruction += content + "\n"
            elif role == 'assistant':
                gemini_messages.append({"role": "model", "parts": [content]})
            elif role == 'user':
                gemini_messages.append({"role": "user", "parts": [content]})
                
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system_instruction.strip() if system_instruction else None
        )
        
        if not gemini_messages:
            return False, "에러: 보낼 메시지가 없습니다."
            
        last_msg = gemini_messages.pop()
        chat = model.start_chat(history=gemini_messages)
        
        response = chat.send_message(
            last_msg['parts'][0], 
            generation_config=genai.types.GenerationConfig(temperature=temperature)
        )
        return True, response.text
    except Exception as e:
        return False, f"Gemini API 오류 발생: {str(e)}"


@games_life_bp.route('/novel')
def novel_maker():
    return render_template('novel.html')


@games_life_bp.route('/api/novel/chat', methods=['POST'])
def api_novel_chat():
    data = request.json
    messages = data.get('messages', [])
    
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "[필수] GEMINI_API_KEY가 없습니다. 환경변수를 확인하세요."})
        
    if not messages:
        return jsonify({"success": False, "error": "메시지 내역이 없습니다."})
        
    system_prompt = """당신은 TRPG 게임의 마스터이자, 사용자와 상호작용하며 흥미진진한 소설을 이끌어가는 뛰어난 작가입니다. 
다음 규칙을 반드시 지켜주세요:
1. 분량을 풍부하게 작성하세요. 매 턴마다 최소 3~4개의 밀도 있는 문단(최소 500자 이상)으로 몰입감 넘치는 묘사와 스토리 진행을 해주세요.
2. 동일한 단어나 비슷한 문장을 절대 반복하지 마세요. 항상 [새로운 사건 발생], [새로운 단서 발견], [새로운 인물 등장] 중 하나를 통해 스토리를 빠르게 앞으로 전진시키세요.
3. 당신의 출력 마지막(스토리 부분)에는 옛날 TV 예능 '인생극장' 처럼 주인공이 직면한 **명확하고 극단적인 두 가지 갈림길(A or B)**을 제공해야 합니다.
4. 선택지는 반드시 다음과 같은 정확한 텍스트 형식으로 스토리 맨 마지막 줄에 작성하세요:
[선택 A] (선택 행동 묘사)
[선택 B] (반대 선택 행동 묘사)
5. 마스터로서 유저의 답변에 맞게 유저의 현재 파라미터(체력, 소지금, 위치, 보유 아이템)를 계산하세요.
6. 반드시 100% 한국어로 대답하며, 아래의 JSON 포맷으로만 응답하세요. 마크다운(` ```json ` 등)으로 절대로 감싸지 마세요.
{
  "story": "(소설 내용 및 마지막 [선택 A] 선택지 텍스트까지 포함. HTML, 마크다운 모두 가능)",
  "status": {
    "hp": (0~100 사이의 숫자 표기),
    "money": "(문자열, 예: 1500 골드, 30달러 등 세계관에 맞는 화폐)",
    "location": "(문자열, 현재 위치한 장소명)",
    "inventory": ["(보유 아이템명1)", "(보유 아이템명2)"]
  }
}"""
    
    if len(messages) > 0 and messages[0].get('role') != 'system':
        messages.insert(0, {"role": "system", "content": system_prompt})
        
    if len(messages) > 0 and messages[-1].get('role') == 'user':
        messages[-1]['content'] += "\n\n(시스템 제약사항: 절대로 방금 문장을 반복하지 말고 상황을 전진시키세요. 엄청나게 구체적이고 긴 분량으로 작성하고, 반드시 지정된 JSON 포맷({'story': ..., 'status': ...})으로만 반환하세요.)"
        
    success, result_text = _call_gemini_chat(api_key, messages, temperature=0.85)
    
    if not success and ("429" in result_text or "exceeded" in result_text.lower()):
        # Fallback to Groq API if Gemini rate limit is hit
        groq_api_key = os.environ.get('GROQ_API_KEY')
        if groq_api_key:
            success, result_text = _call_groq_chat(groq_api_key, messages, temperature=0.8)
            if success:
                result_text = "💡 (제미나이 사용량 초과로 보조 AI가 답합니다) \n\n" + result_text
    
    if success:
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()
        return jsonify({"success": True, "reply": result_text})
    else:
        return jsonify({"success": False, "error": result_text})

# --- ENGLISH TUTOR LOGIC ---

@games_life_bp.route('/game_office')
def game_office():
    return render_template('game_office.html')


@games_life_bp.route('/tarot')
def tarot():
    return render_template('tarot.html')


@games_life_bp.route('/saju')
def saju():
    return render_template('saju.html')


@games_life_bp.route('/archive')
def archive():
    return render_template('archive.html')


@games_life_bp.route('/api/tarot/draw', methods=['POST'])
def api_tarot_draw():
    data = request.json
    prompt = data.get('prompt', '')
    
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "GEMINI_API_KEY가 없습니다."})
        
    try:
        import random
        major_arcana = [
            "바보(The Fool)", "마법사(The Magician)", "여사제(The High Priestess)", "여황제(The Empress)", 
            "황제(The Emperor)", "교황(The Hierophant)", "연인(The Lovers)", "전차(The Chariot)", 
            "힘(Strength)", "은둔자(The Hermit)", "운명의 수레바퀴(Wheel of Fortune)", "정의(Justice)", 
            "매달린 사람(The Hanged Man)", "죽음(Death)", "절제(Temperance)", "악마(The Devil)", 
            "탑(The Tower)", "별(The Star)", "달(The Moon)", "태양(The Sun)", "심판(Judgement)", "세계(The World)"
        ]
        selected_cards = random.sample(major_arcana, 3)
        
        sys_prompt = f"""당신은 신비롭고 영적인 통찰력을 지닌 위대한 타로 마스터입니다.
사용자의 질문: '{prompt}'
당신이 뽑은 운명의 카드 3장:
- 과거의 투영: {selected_cards[0]}
- 현재의 직면: {selected_cards[1]}
- 미래의 계시: {selected_cards[2]}

위 뽑힌 세 장의 타로 카드가 상징하는 본래의 의미들을 엮어, 사용자의 질문에 대한 타로 리딩을 제공하세요. 
**[중요 지시사항]** 지나치게 어렵거나 추상적인 오컬트 용어를 남발하지 마세요. 타로를 난생 처음 보는 사람이나 10대 학생도 한눈에 이해할 수 있도록 아주 쉽고 명확한 일상어로 풀어서 설명해주세요. 카드의 의미를 현실적인 비유를 들어 다정하게 위로하듯 4~5문단으로 여유 있게 적어주세요. 
응답 텍스트에는 복잡한 마크다운을 쓰지 말고, 엔터(줄바꿈)를 통한 자연스러운 문단 구분만 사용하세요."""

        success, text = _call_gemini_chat(api_key, [{"role": "user", "content": sys_prompt}], temperature=0.8)
        if success:
            return jsonify({"success": True, "cards": selected_cards, "reading": text})
        else:
            return jsonify({"success": False, "error": f"통신 실패: {text}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@games_life_bp.route('/api/saju/analyze', methods=['POST'])
def api_saju_analyze():
    data = request.json
    calendar = data.get('calendar', '양력')
    date_str = data.get('date', '')
    time_str = data.get('time', '')
    gender = data.get('gender', '남성')
    
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "GEMINI_API_KEY가 없습니다."})
        
    try:
        sys_prompt = f"""당신은 수십 년 경력의 동양 명리학 학자이자 주역(周易)의 최고 권위자입니다.
사용자 정보:
- 성별: {gender}
- 달력: {calendar}
- 생년월일: {date_str}
- 태어난 시간: {time_str}

위 정보를 바탕으로 육십갑자와 오행, 주역의 괘를 짚어내어, 이 사람의 운명과 기운을 [일간, 주간, 월간, 년간] 4가지 시점 각각에 대하여 [총평, 금전운, 직장/사업운, 연애운, 인간관계] 5대 영역으로 상세하게 풀이해 주세요. 
단순한 뻔한 소리가 아니라, 마치 오랫동안 산 수행자가 조언해주듯 뼈 때리면서도 신비롭고 현실적인 톤을 유지하세요. 각 항목당 2~3문장으로 간결하지만 타격감 있게 작성하세요.
**[중요 지시사항]** 사주 풀이 중에 한자(예: 癸卯, 財星 등)를 사용할 때는 반드시 괄호 안에 한글 뜻과 음(예: 계묘, 재성)을 병기하고 의미를 쉽게 풀어주세요. 한자를 전혀 모르는 사람도 술술 읽을 수 있어야 합니다.
반드시 아래 JSON 형식으로만 완벽하게 응답해야 합니다. (daily, weekly, monthly, yearly 내부의 5가지 키를 엄수하세요)
{{
  "daily": {{ "summary": "오늘(일간)의 전체 운세와 조언", "wealth": "오늘의 금전운/재물 기운", "career": "오늘의 직장/학업/사업운", "love": "오늘의 연애운/이성 관계", "people": "오늘의 전반적 인간관계 운" }},
  "weekly": {{ "summary": "이번 주 전체 운세와 흐름", "wealth": "이번 주 금전운 흐름", "career": "이번 주 직장/사업운 목표", "love": "이번 주 연애운 포인트", "people": "이번 주 조심하거나 기대할 인간관계" }},
  "monthly": {{ "summary": "이번 달 전체 운세와 핵심 과제", "wealth": "이번 달 금전운 전략", "career": "이번 달 직장/사업운 변화", "love": "이번 달 연애운 흐름", "people": "이번 달 귀인과 악연" }},
  "yearly": {{ "summary": "올해 전체 운세와 터닝 포인트", "wealth": "올해 재물운의 큰 그림", "career": "올해 직업/사업운의 향방", "love": "올해 연애운의 결정적 순간", "people": "올해 내 곁에 남을 사람과 떠날 사람" }}
}}"""

        success, text = _call_gemini_chat(api_key, [{"role": "user", "content": sys_prompt}], temperature=0.6)
        if success:
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            import json
            j_data = json.loads(text)
            return jsonify({"success": True, "data": j_data})
        else:
            return jsonify({"success": False, "error": f"통신 실패: {text}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@games_life_bp.route('/face')
def face_reading():
    return render_template('face.html')


@games_life_bp.route('/api/face/analyze', methods=['POST'])
def api_face_analyze():
    data = request.json
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "GEMINI_API_KEY가 없습니다."})
        
    image_b64 = data.get('image', '')
    if not image_b64:
        return jsonify({"success": False, "error": "이미지가 입력되지 않았습니다."})
        
    sys_prompt = """당신은 조선시대 저잣거리에서 돗자리를 깔고 관상을 보는 팩트폭력 전문 관상가입니다. 
말투는 사극풍과 재미있는 인터넷 밈, 반말을 섞어서 사용하며 아주 신랄하고 뼈를 때리는 유머러스한 느낌이어야 합니다. (예: "허허, 이마를 보아하니 고집이 아주 소를 잡아먹겠구만!", "이빨을 보아하니 식복은 타고났네 그려.")

사용자가 올린 얼굴 사진의 이목구비와 비율, 특징을 분석하여 관상 결과를 도출하세요.
반드시 아래 JSON 형식으로만 응답해야 합니다.
{
  "features": "얼굴의 가장 눈에 띄는 생김새 특징 2~3가지 분석 (사극풍 팩폭)",
  "wealth": "재물운 평가 (뼈때리는 일침 포함)",
  "love": "애정운/연애운 평가",
  "career": "직장운/사업운 평가 (또는 적성 추천)",
  "verdict": "내가 왕이 될 상인가? 에 대한 최종 판결 한 줄"
}"""

    try:
        success, text = _call_gemini_vision(api_key, sys_prompt, image_b64)
        if success:
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            import json
            j_data = json.loads(text)
            return jsonify({"success": True, "data": j_data})
        else:
            return jsonify({"success": False, "error": f"분석 실패: {text}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


def _call_gemini_vision(api_key, text_prompt, base64_image, temperature=0.7):
    import google.generativeai as genai
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(
            [
                {"mime_type": "image/jpeg", "data": base64_image},
                text_prompt
            ],
            generation_config=genai.types.GenerationConfig(temperature=temperature)
        )
        return True, response.text
    except Exception as e:
        return False, str(e)


@games_life_bp.route('/dream')
def dream_view():
    return render_template('dream.html')


@games_life_bp.route('/api/dream/analyze', methods=['POST'])
def api_dream_analyze():
    data = request.json
    dream = data.get('dream', '')
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key: return jsonify({"success": False, "error": "API Key missing"})
    
    prompt = f"""당신은 무속 신앙과 현대 심리학에 정통한 전설적인 꿈 해몽가입니다.
사용자의 꿈: "{dream}"
위 꿈을 해석하여 아래 JSON 형식으로 응답하세요.
{{
  "tradition": "전통적인 길몽/흉몽의 관점 해석 (약 3문장)",
  "psycho": "현대 심리학 및 무의식적 스트레스 관점 해석 (약 3문장)",
  "lotto": "우주의 기운이 담긴 로또 번호 6개 (단순히 숫자만 콤마로, 예: 4, 12, 23, 29, 33, 41)"
}}"""
    success, text = _call_gemini_chat(api_key, [{"role":"user", "content":prompt}], 0.8)
    if success:
        if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
        import json
        try: return jsonify({"success": True, "data": json.loads(text)})
        except: return jsonify({"success": False, "error": "JSON 파싱 실패"})
    return jsonify({"success": False, "error": text})


@games_life_bp.route('/therapist')
def therapist_view(): return render_template('therapist.html')


@games_life_bp.route('/api/therapist/counsel', methods=['POST'])
def api_therapist_counsel():
    api_key = os.environ.get('GEMINI_API_KEY')
    history = request.json.get('history', [])
    
    sys_prompt = "당신은 국민 심리상담가 오은영 박사님처럼 한없이 따뜻하고 무조건 내 편이 되어주는 대나무숲 요정입니다. 사용자의 고민을 깊이 공감하고 위로하는 대화를 진행하세요."
    messages = [{"role": "system", "content": sys_prompt}]
    
    for msg in history:
        messages.append({"role": msg['role'], "content": msg['content']})
        
    success, text = _call_gemini_chat(api_key, messages, 0.7)
    return jsonify({"success": success, "reply": text, "error": text if not success else ""})


@games_life_bp.route('/fashion')
def fashion_view(): return render_template('fashion.html')


@games_life_bp.route('/api/fashion/evaluate', methods=['POST'])
def api_fashion():
    mode = request.json.get('mode', 'fashion')
    b64 = request.json.get('image', '')
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key: return jsonify({"success": False, "error": "API Key missing"})
    
    if mode == 'fashion':
        sys_p = """이 사진의 패션 코디(착장)를 매의 눈으로 분석하세요. 세계 최고의 독설가 패션 디자이너처럼 잔인하고 솔직하게 평가하세요. 100점 만점 점수와 피드백을 JSON으로 주세요. {"score": "점수", "feedback": "팩트폭행 사이다 피드백"}"""
    else:
        sys_p = """이 사람의 얼굴상(인상/이미지)이나 분위기를 재미있게 관상/매력도 관점에서 평가하세요. 철학관 원장님 혹은 독설가 연애코치처럼 돌직구로 평가하세요. 100점 만점 점수와 피드백을 JSON으로 주세요. {"score": "점수", "feedback": "돌직구 피드백"}"""
        
    success, text = _call_gemini_vision(api_key, sys_p, b64)
    if success:
        if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
        import json
        try: return jsonify({"success": True, "data": json.loads(text)})
        except: return jsonify({"success": False, "error": "JSON 파싱 실패"})
    return jsonify({"success": False, "error": text})


@games_life_bp.route('/love')
def love_view(): return render_template('love.html')


@games_life_bp.route('/api/love/analyze', methods=['POST'])
def api_love_analyze():
    b64 = request.json.get('image', '')
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key: return jsonify({"success": False, "error": "API Key missing"})
    
    sys_p = """당신은 100전 100승의 전설적인 연애 코치입니다. 사용자가 올린 카톡 대화 화면 캡처를 보고, 상대방의 답장 길이/속도, 단답 여부, 이모티콘 사용량 등을 면밀히 스캔하세요. 이것이 '그린라이트 썸'인지, '답정너 짝사랑'인지, 아니면 '위험한 어장관리'인지 무자비하게 팩트 폭행하며 알려주세요.
반드시 아래 JSON 형식으로 반환하세요.
{
  "score": "그린라이트 확률 점수 (예: 85, 30 등 숫자만)",
  "verdict": "짧은 판정 결과 (예: '완벽한 썸', '혼자만의 짝사랑', '위험한 어장관리')",
  "analysis": "구체적인 카톡 분석 내용과 뼈 때리는 조언 (3-4문장)"
}"""
    success, text = _call_gemini_vision(api_key, sys_p, b64)
    if success:
        if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
        import json
        try: return jsonify({"success": True, "data": json.loads(text)})
        except: return jsonify({"success": False, "error": "JSON 파싱 실패"})
    return jsonify({"success": False, "error": text})


@games_life_bp.route('/diet')
def diet_view(): return render_template('diet.html')


@games_life_bp.route('/api/diet/analyze', methods=['POST'])
def api_diet_analyze():
    b64 = request.json.get('image', '')
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key: return jsonify({"success": False, "error": "API Key missing"})
    
    sys_p = """당신은 호랑이 다이어트 PT 코치(김종국 모드)입니다. 사용자가 오늘 먹은 음식 사진이나 배달 영수증을 올렸습니다. 먹은 메뉴와 사진을 스캔해서 대략적인 섭취 칼로리를 유추하고, 이런 걸 먹다니 제정신이냐며 눈물 쏙 빼게 혼나는 팩트 폭행 잔소리를 날려주세요. 그리고 내일 어떻게 속죄해야 하는지 처방해주세요.
반드시 아래 JSON 형식으로 반환하세요.
{
  "calories": "예상 칼로리 (예: 1200, 800 등 숫자만)",
  "roasts": "양심의 가책을 느끼게 하는 호통과 잔소리 (3-4문장)",
  "workout_plan": "내일 반드시 해야 할 속죄 플랜 (예: 런닝머신 2시간, 점심은 방울토마토 3알)"
}"""
    success, text = _call_gemini_vision(api_key, sys_p, b64)
    if success:
        if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
        import json
        try: return jsonify({"success": True, "data": json.loads(text)})
        except: return jsonify({"success": False, "error": "JSON 파싱 실패"})
    return jsonify({"success": False, "error": text})


@games_life_bp.route('/diary')
def diary_view(): return render_template('diary.html')


@games_life_bp.route('/api/diary/chat', methods=['POST'])
def api_diary_chat():
    history = request.json.get('history', [])
    api_key = os.environ.get('GEMINI_API_KEY')
    
    convo_text = ""
    for msg in history:
        sender = "AI(당신)" if msg.get("role") == "ai" else "사용자"
        convo_text += f"{sender}: {msg.get('content')}\n"
    
    sys_p = f"""지금까지의 일기장 대화 내역입니다:
{convo_text}

[작성 규칙]
1. 위 대화의 흐름을 완벽히 숙지하고, 사용자의 마지막 대답에 어울리는 새로운 꼬리 질문을 '딱 1개만' 던지세요.
2. 당신이 이전에 이미 물어봤던 질문 패턴을 앵무새처럼 절대 반복하지 마세요. (예: "기분이 어땠어?"를 계속 묻지 말 것)
3. 대답이 짧다면("맞아", "응" 등) 화제를 살짝 전환해서 "그나저나 오늘 밥은 뭐 먹었어?" 처럼 자연스럽게 다른 일상 요소를 캐물어보세요.
4. 친구처럼 편안하고 짧게 대화체로 물어보세요."""
        
    success, text = _call_gemini_chat(api_key, [{"role":"user", "content":sys_p}], 0.7)
    return jsonify({"success": success, "reply": text, "error": text if not success else ""})


@games_life_bp.route('/api/diary/compile', methods=['POST'])
def api_diary_compile():
    history = request.json.get('history', [])
    api_key = os.environ.get('GEMINI_API_KEY')
    
    user_answers = [msg.get("content") for msg in history if msg.get("role") == "user"]
    ans_text = "\n".join(f"- {a}" for a in user_answers)
    
    sys_p = f"""당신은 평범한 사람의 하루를 대필해주는 일기 작가입니다. 
다음 사용자의 단답형 응답들을 바탕으로 '오늘의 일기'를 한 편 대필해주세요. 

[사용자 응답 내역]
{ans_text}

[작성 규칙 - 매우 중요]
1. 너무 거창하고 문학적인 표현(예: 폐부 깊숙이 스며드는, 투영, 그늘을 드리웠다 등)은 절대 금지합니다.
2. 진짜 사람이 쓴 것처럼 담백하고 캐주얼한 일상체(평어체, ~했다, ~음, ~이다)로 작성하세요. 혼잣말 하듯이 속마음과 감정이 솔직하게 드러나야 합니다.
3. 길이는 2~3문단 정도로 짧고 간결하게 작성하세요.
4. 마크다운 기호 없이 순수 텍스트 줄바꿈만 사용하세요."""
    success, text = _call_gemini_chat(api_key, [{"role":"user", "content":sys_p}], 0.7)
    return jsonify({"success": success, "diary": text, "error": text if not success else ""})


@games_life_bp.route('/api/diary/notion', methods=['POST'])
def api_diary_notion():
    data = request.json
    notion_key = data.get('notion_key', '')
    db_id = data.get('db_id', '')
    title = data.get('title', '일기')
    content = data.get('content', '')
    
    import requests
    headers = {
        "Authorization": f"Bearer {notion_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    paragraphs = content.split('\n')
    children = []
    for p in paragraphs:
        if p.strip():
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": { "rich_text": [ { "type": "text", "text": { "content": p.strip() } } ] }
            })
            
    payload = {
        "parent": { "database_id": db_id },
        "properties": {
            "title": { "title": [ { "text": { "content": title } } ] }
        },
        "children": children
    }
    
    try:
        res = requests.post("https://api.notion.com/v1/pages", json=payload, headers=headers)
        if res.status_code == 200:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": res.text})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@games_life_bp.route('/mz_translator')
def mz_translator_view():
    return render_template('mz_translator.html')

@games_life_bp.route('/api/mz_translate', methods=['POST'])
def api_mz_translate():
    text = request.json.get('text', '')
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "API Key missing"})
    
    sys_p = """당신은 트렌드에 극도로 민감한 20대 초반 힙스터 MZ 사원입니다. 
사용자가 입력하는 딱딱한 꼰대어, 아재개그, 혹은 너무 평범한 텍스트를 요즘 유행하는 최신 밈과 신조어(예: 폼 미쳤다, 완전 럭키비키잖아, 억까, 긁?, 킹받네, 알잘딱깔센, 디토, 뇌빼기 등)를 듬뿍 넣어서 찰진 'MZ 언어'로 번역해주세요. 
[번역 규칙]
1. 너무 길게 번역하지 말고 원문의 의미는 통하되 분위기를 완전히 힙하게 바꾸세요.
2. 어울리는 이모지를 적극적으로 섞어서 작성하세요.
3. 번역된 텍스트만 출력하세요. 설명이나 부연 설명은 절대 금지."""
    
    success, reply = _call_gemini_chat(api_key, [{"role": "user", "content": f"{sys_p}\n\n[입력 텍스트]: {text}"}], 0.8)
    return jsonify({"success": success, "translated": reply, "error": reply if not success else ""})

if __name__ == '__main__':
    # When hosted on Render, Gunicorn parses the app instance. 
    # This block is for simple local testing via `python main.py`
    import os
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port, debug=False)
