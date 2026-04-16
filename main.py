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
# --- GLOBAL SETTINGS ---
ssl._create_default_https_context = ssl._create_unverified_context

import json

krx_dict = {}
try:
    with open('krx_tickers.json', 'r', encoding='utf-8') as f:
        krx_data = json.load(f)
        for item in krx_data:
            krx_dict[item['Name']] = str(item['Code']).zfill(6)
except Exception as e:
    print("Warning: failed to load krx_tickers.json:", e)

# --- STOCK APP LOGIC ---
def get_ticker_from_name(name):
    t = krx_dict.get(name, name)
    if isinstance(t, str) and (t.endswith('.KS') or t.endswith('.KQ')):
        t = t[:-3]
    return t

@app.route('/api/stock')
def get_stock_data():
    raw_ticker = request.args.get('ticker', '').strip()
    period = request.args.get('period', '2y')
    prediction_days = 30
    
    try:
        ticker = get_ticker_from_name(raw_ticker)
        
        days = 365 * 2
        if period == '1mo': days = 30
        elif period == '3mo': days = 90
        elif period == '6mo': days = 180
        elif period == '1y': days = 365
        elif period == '5y': days = 365 * 5
        
        start_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
        hist = fdr.DataReader(ticker, start_date)
        
        if hist is None or hist.empty:
            return jsonify({'success': False, 'error': f"'{raw_ticker}'의 데이터를 찾을 수 없습니다. 종목명 또는 코드를 정확히 확인해주세요."})
        
        hist = hist.reset_index()
        hist['Date'] = pd.to_datetime(hist['Date'])
        
        hist['SMA_20'] = hist['Close'].rolling(window=20).mean()
        hist['STD_20'] = hist['Close'].rolling(window=20).std()
        hist['BB_Upper'] = hist['SMA_20'] + (hist['STD_20'] * 2)
        hist['BB_Lower'] = hist['SMA_20'] - (hist['STD_20'] * 2)
        
        hist['SMA_50'] = hist['Close'].rolling(window=50).mean()
        
        hist['EMA_12'] = hist['Close'].ewm(span=12, adjust=False).mean()
        hist['EMA_26'] = hist['Close'].ewm(span=26, adjust=False).mean()
        hist['MACD'] = hist['EMA_12'] - hist['EMA_26']
        hist['MACD_Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
        
        hist['Vol_MA_20'] = hist['Volume'].rolling(window=20).mean()
        
        delta = hist['Close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
        rs = avg_gain / avg_loss
        hist['RSI'] = 100 - (100 / (1 + rs))
        
        historical_data = []
        for index, row in hist.iterrows():
            c_val = float(row['Close']) if not pd.isna(row['Close']) else None
            v_val = float(row['Volume']) if not pd.isna(row['Volume']) else 0
            if c_val is None or np.isnan(c_val):
                continue
                
            s20_val = float(row['SMA_20']) if not pd.isna(row['SMA_20']) else None
            if s20_val is not None and np.isnan(s20_val): s20_val = None
            
            s50_val = float(row['SMA_50']) if not pd.isna(row['SMA_50']) else None
            if s50_val is not None and np.isnan(s50_val): s50_val = None
                
            historical_data.append({
                'date': row['Date'].strftime('%Y-%m-%d'),
                'close': c_val,
                'volume': v_val,
                'sma_20': s20_val,
                'sma_50': s50_val
            })
            
        recent_data = hist.tail(126).copy() if len(hist) > 126 else hist.copy()
        recent_data = recent_data.dropna(subset=['Close'])
        
        if len(recent_data) > 30:
            x_vals = np.arange(len(recent_data)).reshape(-1, 1)
            y_vals = recent_data['Close'].values
            
            model = LinearRegression()
            model.fit(x_vals, y_vals)
            
            last_date = recent_data['Date'].iloc[-1]
            last_price = recent_data['Close'].iloc[-1]
            
            returns = recent_data['Close'].pct_change().dropna()
            daily_volatility = returns.std()
            
            future_dates = pd.bdate_range(start=last_date + pd.Timedelta(days=1), periods=prediction_days)
            
            predictions = [{
                'date': last_date.strftime('%Y-%m-%d'),
                'predicted_close': float(last_price),
                'upper_band': float(last_price),
                'lower_band': float(last_price)
            }]
            
            future_x = np.arange(len(recent_data), len(recent_data) + prediction_days).reshape(-1, 1)
            future_y = model.predict(future_x)
            
            for i, p_date in enumerate(future_dates):
                center = float(future_y[i]) if future_y[i] > 0 else 0.0
                days_ahead = i + 1
                expansion = daily_volatility * center * np.sqrt(days_ahead) * 1.5
                
                predictions.append({
                    'date': p_date.strftime('%Y-%m-%d'),
                    'predicted_close': center,
                    'upper_band': center + expansion,
                    'lower_band': max(center - expansion, 0.0)
                })
                
            past_predictions = []
            if len(recent_data) > 60:
                train_data = recent_data.iloc[:-30]
                test_data = recent_data.iloc[-30:] 
                
                x_vals_bk = np.arange(len(train_data)).reshape(-1, 1)
                y_vals_bk = train_data['Close'].values
                
                model_bk = LinearRegression()
                model_bk.fit(x_vals_bk, y_vals_bk)
                
                bk_last_price = train_data['Close'].iloc[-1]
                
                past_predictions.append({
                    'date': train_data['Date'].iloc[-1].strftime('%Y-%m-%d'),
                    'backtest_close': float(bk_last_price)
                })
                
                bk_future_x = np.arange(len(train_data), len(train_data) + len(test_data)).reshape(-1, 1)
                bk_future_y = model_bk.predict(bk_future_x)
                
                for i, row in enumerate(test_data.itertuples()):
                    bk_center = float(bk_future_y[i]) if bk_future_y[i] > 0 else 0.0
                    past_predictions.append({
                        'date': row.Date.strftime('%Y-%m-%d'),
                        'backtest_close': bk_center
                    })
        else:
            predictions = []
            past_predictions = []
            
        ai_data = None
        vol_trend_str = "데이터 부족"
        vol_ratio = 100
        if len(recent_data) > 30 and os.environ.get('GROQ_API_KEY'):
            api_key = os.environ.get('GROQ_API_KEY')
            current_p = recent_data['Close'].iloc[-1]
            high_1m = recent_data['High'].tail(21).max() if 'High' in recent_data else current_p
            low_1m = recent_data['Low'].tail(21).min() if 'Low' in recent_data else current_p
            sma50 = hist['SMA_50'].iloc[-1]
            rsi = hist['RSI'].iloc[-1]
            
            bb_upper = hist['BB_Upper'].iloc[-1]
            bb_lower = hist['BB_Lower'].iloc[-1]
            macd = hist['MACD'].iloc[-1]
            macd_signal = hist['MACD_Signal'].iloc[-1]
            vol_today = hist['Volume'].iloc[-1]
            vol_ma20 = hist['Vol_MA_20'].iloc[-1]
            
            sma50_str = f"{sma50:.2f}" if pd.notnull(sma50) else "N/A"
            rsi_str = f"{rsi:.2f}" if pd.notnull(rsi) else "N/A"
            bb_upper_str = f"{bb_upper:.2f}" if pd.notnull(bb_upper) else "N/A"
            bb_lower_str = f"{bb_lower:.2f}" if pd.notnull(bb_lower) else "N/A"
            macd_str = f"{macd:.2f}" if pd.notnull(macd) else "N/A"
            macd_sig_str = f"{macd_signal:.2f}" if pd.notnull(macd_signal) else "N/A"
            
            vol_ratio = (vol_today / vol_ma20 * 100) if pd.notnull(vol_ma20) and vol_ma20 > 0 else 100
            
            if vol_ratio >= 150: vol_trend_str = "거래량 폭발 (수급 집중) 💥"
            elif vol_ratio >= 110: vol_trend_str = "거래량 증가 추세 📈"
            elif vol_ratio <= 70: vol_trend_str = "거래량 대폭 감소 📉"
            elif vol_ratio <= 90: vol_trend_str = "거래량 감소 추세 🔻"
            else: vol_trend_str = "평균 수준의 거래량"
            
            p_prompt = f"""당신은 왕초보들을 가르치는 동네 주식 학원의 가장 다정하고 친절한 1타 강사입니다.
종목: {ticker} ({raw_ticker})
현재가: {current_p:.2f}
최근 1개월 최고가: {high_1m:.2f} / 최저가: {low_1m:.2f}
50일 이동평균선: {sma50_str}
현재 RSI (14일): {rsi_str}
볼린저밴드 (20일): 상단 {bb_upper_str} / 하단 {bb_lower_str}
MACD 추세: {macd_str} (시그널 {macd_sig_str})
최근 거래량: {vol_trend_str} (20일 평균 대비 {vol_ratio:.1f}% 수준)

위 기술적 지표들을 종합하여 향후 차트 전개 방향을 아주아주 쉽게 예측하세요. 
반드시 아래 JSON 형식으로만 응답해야 합니다.
{{
  "analysis": "오늘 주식을 처음 시작한 초등학생도 고개를 끄덕일 수 있는 아주 쉽고 다정한 차트 분석 (4~5문장). 주의: 한자(Hanja)나 중국어를 절대 단 한 글자도 쓰지 말고 무조건 100% 한글로만 작성하세요! RSI, 볼린저밴드, MACD, 최근 거래량 현황(증가/감소 등)을 설명할 때는 반드시 그 숨은 뜻을 (예: '거래량이 평소보다 대폭 줄어들어서 사람들의 관심이 식었다는 뜻이에요~' 등) 완벽하게 풀어서 설명해야 합니다. 절대로 전문가처럼 딱딱하게 말하지 말고, 초보자 눈높이에서 해석의 '결론'을 떠먹여 주세요.",
  "target_price": 1개월 뒤 현실적인 목표가(숫자만),
  "stop_loss": 현재 복합 지지라인 기반의 명확한 손절가(숫자만)
}}"""
            try:
                success, text = _call_groq(api_key, p_prompt)
                if success:
                    if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
                    elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
                    import json
                    ai_data = json.loads(text)
            except Exception as e:
                print(f"AI Chart Error: {e}")
            
        return jsonify({
            'success': True,
            'ticker': ticker,
            'original_ticker': raw_ticker,
            'historical': historical_data,
            'predictions': predictions,
            'past_predictions': past_predictions,
            'pred_days': prediction_days,
            'ai_analysis': ai_data,
            'volume_trend': vol_trend_str,
            'volume_ratio': vol_ratio
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# --- YOUTUBE EXTRACTOR LOGIC ---
def extract_channel_videos(channel_input, limit=50):
    api_key = os.environ.get('YOUTUBE_API_KEY')
    if not api_key:
        return {"success": False, "error": "[필수] 공식 YouTube API 키가 없습니다. Render 설정의 Environment에 가서 YOUTUBE_API_KEY를 등록해주세요."}
        
    channel_input = channel_input.strip()
    
    # 1. Resolve to channel ID (UC...)
    channel_id = None
    if channel_input.startswith('UC') and len(channel_input) == 24:
        channel_id = channel_input
    elif 'youtube.com/channel/UC' in channel_input:
        channel_id = 'UC' + channel_input.split('channel/UC')[1].split('/')[0].split('?')[0]
    else:
        handle = channel_input
        if 'youtube.com/@' in handle:
            handle = '@' + handle.split('youtube.com/@')[1].split('/')[0].split('?')[0]
            
        # 사용자가 명시적으로 '@'를 붙였거나, URL 분석 결과 '@핸들'이 추출된 경우에만 채널 고유 ID를 가져오도록 시도
        if handle.startswith('@'):
            channels_url = f"https://youtube.googleapis.com/youtube/v3/channels?part=id&forHandle={handle}&key={api_key}"
            try:
                resp = requests.get(channels_url)
                data = resp.json()
                if 'items' in data and len(data['items']) > 0:
                    channel_id = data['items'][0]['id']
            except Exception as e:
                pass
            
    is_search_query = False
    search_query = ""
    if not channel_id:
        # If it doesn't look like a channel, treat as a generic search query
        is_search_query = True
        search_query = channel_input
        
    # 2. Fetch Videos
    import html
    video_ids = []
    video_titles = {}
    
    next_page_token = ""
    try:
        while len(video_ids) < limit:
            q_limit = min(50, limit - len(video_ids))
            if is_search_query:
                import urllib.parse
                sq = urllib.parse.quote(search_query)
                # For generic search, order by relevance is usually better, but viewCount works if they want 'popular' videos of that keyword
                search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={sq}&maxResults={q_limit}&order=relevance&type=video&key={api_key}"
            else:
                search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={channel_id}&maxResults={q_limit}&order=viewCount&type=video&key={api_key}"
                
            if next_page_token:
                search_url += f"&pageToken={next_page_token}"
                
            resp = requests.get(search_url)
            data = resp.json()
            
            if 'error' in data:
                err_reason = data['error'].get('message', '알 수 없는 오류')
                return {"success": False, "error": f"API 통신 오류: {err_reason}"}
                
            items = data.get('items', [])
            if not items:
                break
                
            for item in items:
                video_id = item['id'].get('videoId')
                if not video_id: continue
                if video_id not in video_titles:
                    video_ids.append(video_id)
                    video_titles[video_id] = html.unescape(item['snippet']['title'])
            
            next_page_token = data.get('nextPageToken')
            if not next_page_token:
                break
                
            if len(video_ids) >= limit:
                break
                
        if not video_ids:
            if is_search_query:
                return {"success": False, "error": f"검색어 '{search_query}'에 대한 동영상을 찾을 수 없습니다."}
            else:
                return {"success": False, "error": "해당 채널에 동영상이 존재하지 않거나 가져올 수 없습니다."}
            
        # 3. Get exact statistics for sorting (Batch API accepts max 50 per request)
        stats_data_items = []
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i+50]
            stats_url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={','.join(chunk)}&key={api_key}"
            stats_resp = requests.get(stats_url)
            s_data = stats_resp.json()
            if 'items' in s_data:
                stats_data_items.extend(s_data['items'])
        
        results = []
        for item in stats_data_items:
            v_id = item['id']
            views = int(item['statistics'].get('viewCount', 0))
            results.append({
                'id': v_id,
                'title': video_titles.get(v_id, 'No Title'),
                'url': f"https://www.youtube.com/watch?v={v_id}",
                'view_count': views
            })
            
        # 4. Strict absolute sort by viewCount descending
        results.sort(key=lambda x: x['view_count'], reverse=True)
            
        return {"success": True, "data": results[:limit], "channel": channel_input, "is_search": is_search_query}
        
    except Exception as e:
        return {"success": False, "error": f"유튜브 통신 중 서버 오류가 발생했습니다: {str(e)}"}

@app.route('/api/extract', methods=['POST'])
def extract():
    data = request.json
    channel_id = data.get('channel_id')
    limit = int(data.get('limit', 50))
    if not channel_id:
        return jsonify({"success": False, "error": "채널명을 입력해주세요."})
    
    result = extract_channel_videos(channel_id, limit)
    return jsonify(result)

# --- PROMPT OPTIMIZER LOGIC ---
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

def _call_groq(api_key, sys_prompt, system_role="당신은 세계 최고의 프롬프트 엔지니어입니다."):
    import requests
    model_name = get_best_groq_model(api_key)
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_role},
            {"role": "user", "content": sys_prompt}
        ],
        "temperature": 0.7
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

@app.route('/api/prompt/ask', methods=['POST'])
def prompt_ask():
    data = request.json
    idea = data.get('idea', '')
    history = data.get('history', [])
    q_index = data.get('questionIndex', 1)
    
    if not idea:
        return jsonify({"success": False, "error": "아이디어를 입력해주세요."})
        
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "[필수] Groq API 키가 없습니다. Render Environment에 GROQ_API_KEY를 등록해주세요."})
        
    try:
        if history:
            history_text = "\n".join([f"Q: {item['question']}\nA: {item['answer']}" for item in history])
        else:
            history_text = "없음"
            
        sys_prompt = f"""당신은 세계 최고의 프롬프트 엔지니어입니다.
초기 아이디어: "{idea}"
지금까지 진행된 질의응답:
{history_text}

이 사용자의 아이디어를 완벽한 프롬프트로 발전시키기 위해, 추가로 물어봐야 할 가장 핵심적인 **단 하나의 질문**을 생성하세요.
이 질문은 {q_index}번째 질문입니다. (총 5개의 질문을 할 예정입니다.)
답변을 쉽게 할 수 있도록 구체적인 예시도 포함해 주세요.

반드시 아래의 단일 JSON 객체 형식으로만 응답해야 합니다. 다른 말은 절대 덧붙이지 마세요.
{{
  "question": "핵심 질문 내용...",
  "example": "예: ... 와 같이 적어주세요."
}}"""
        success, text = _call_groq(api_key, sys_prompt)
        
        if not success:
            return jsonify({"success": False, "error": f"모든 AI 모델 통신 실패 (최종 오류): {text}"})
            
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        import json
        question_data = json.loads(text)
        return jsonify({"success": True, "question": question_data})
    except Exception as e:
        return jsonify({"success": False, "error": f"AI 통신 오류: {str(e)}"})

@app.route('/api/prompt/generate', methods=['POST'])
def prompt_generate():
    data = request.json
    idea = data.get('idea', '')
    answers = data.get('answers', [])
    
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "API 키가 없습니다."})
        
    try:
        answers_text = "\n".join([f"Q: {a['question']}\nA: {a['answer']}" for a in answers])
        
        sys_prompt = f"""초기 아이디어: {idea}

사용자의 추가 답변:
{answers_text}

위 내용을 바탕으로 사용자가 ChatGPT나 Claude 등에 그대로 복사해서 붙여넣기만 하면 최고의 결과가 나올 수 있는 '궁극의 마스터 프롬프트'를 마크다운 형태의 코드 블록(```) 영역 안에 작성해주세요.
[역할 지정], [구체적 목적], [세부 규칙], [출력 양식] 등 최신 프롬프트 가이드라인을 잘 지켜서 풍성하고 디테일하게 작성해주세요."""

        success, final_text = _call_groq(api_key, sys_prompt)
        
        if not success:
            return jsonify({"success": False, "error": f"모든 AI 모델 통신 실패 (최종 오류): {final_text}"})
            
        return jsonify({"success": True, "prompt": final_text})
    except Exception as e:
        return jsonify({"success": False, "error": f"AI 통신 오류: {str(e)}"})

# --- STATS & COMMENTS LOGIC ---
STATS_FILE = 'stats.json'
COMMENTS_FILE = 'comments.json'

def get_stats():
    if not os.path.exists(STATS_FILE):
        return {"total": 0, "today": 0, "date": datetime.datetime.now().strftime('%Y-%m-%d')}
    try:
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"total": 0, "today": 0, "date": datetime.datetime.now().strftime('%Y-%m-%d')}

def save_stats(st):
    try:
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(st, f)
    except:
        pass

def track_visitor():
    st = get_stats()
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    st['total'] += 1
    if st.get('date') != today_str:
        st['date'] = today_str
        st['today'] = 1
    else:
        st['today'] += 1
    save_stats(st)
    return st

# --- ROUTES ---
@app.route('/')
def home():
    st = track_visitor()
    return render_template('home.html', stats=st)

@app.route('/api/comments', methods=['GET', 'POST'])
def api_comments():
    comments = []
    if os.path.exists(COMMENTS_FILE):
        try:
            with open(COMMENTS_FILE, 'r', encoding='utf-8') as f:
                comments = json.load(f)
        except:
            pass
            
    if request.method == 'GET':
        return jsonify({"success": True, "comments": comments})
        
    if request.method == 'POST':
        data = request.json
        author = data.get('author', '익명').strip()
        text = data.get('text', '').strip()
        if not author: author = "익명"
        if not text: return jsonify({"success": False, "error": "내용을 입력해주세요."})
        
        new_comment = {
            "id": str(uuid.uuid4()),
            "author": author,
            "text": text,
            "date": datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        comments.insert(0, new_comment)
        comments = comments[:100] # 최근 100개만 유지
        
        try:
            with open(COMMENTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(comments, f, ensure_ascii=False)
            return jsonify({"success": True, "comments": comments})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

@app.route('/restaurant')
def restaurant():
    return render_template('restaurant.html')

@app.route('/youtube')
def youtube():
    return render_template('youtube.html')

@app.route('/stock')
def stock():
    return render_template('stock.html')

@app.route('/prompt')
def prompt():
    return render_template('prompt.html')

@app.route('/lotto')
def lotto():
    return render_template('lotto.html')

@app.route('/api/lotto', methods=['GET'])
def api_lotto():
    import random
    # 역대 가장 많이 나온 10개 번호 (최근까지의 누적 통계 기준)
    top_10 = [34, 43, 12, 27, 1, 13, 17, 39, 33, 18]
    # 역대 가장 적게 나온 10개 번호
    bottom_10 = [9, 22, 29, 23, 28, 8, 30, 32, 42, 25]
    
    # 상위 10개에서 6개 뽑기 5조합
    top_combs = []
    for _ in range(5):
        top_combs.append(sorted(random.sample(top_10, 6)))
        
    # 하위 10개에서 6개 뽑기 5조합
    bottom_combs = []
    for _ in range(5):
        bottom_combs.append(sorted(random.sample(bottom_10, 6)))
        
    return jsonify({
        "success": True,
        "top_10_pool": top_10,
        "bottom_10_pool": bottom_10,
        "top_combinations": top_combs,
        "bottom_combinations": bottom_combs
    })

@app.route('/shorts')
def shorts_maker():
    return render_template('shorts_maker.html')

@app.route('/novel')
def novel_maker():
    return render_template('novel.html')

@app.route('/api/novel/chat', methods=['POST'])
def api_novel_chat():
    data = request.json
    messages = data.get('messages', [])
    
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "[필수] GEMINI_API_KEY가 없습니다. 환경변수를 확인하세요."})
        
    if not messages:
        return jsonify({"success": False, "error": "메시지 내역이 없습니다."})
        
    system_prompt = """당신은 TRPG 게임의 마스터이자, 사용자와 상호작용하며 흥미진진한 소설을 이끌어가는 작가입니다. 
다음 규칙을 반드시 지켜주세요:
1. 몰입감 넘치는 묘사와 생생한 전개를 유지하세요. (주변 환경, 인물의 심리, 색감 등을 아주 디테일하고 길게 묘사할 것)
2. 절대 유저의 행동이나 대답을 당신이 대신 작성하지 마세요.
3. 당신(마스터)의 출력 마지막 문장은 항상 유저에게 위기 상황 대처나 선택을 묻는 질문으로 끝내세요.
4. 사용자의 선택 결과를 적극 반영해 다음 상황을 전개하세요.
5. [가장 중요] 반드시 자연스러운 100% 한국어(Korean)로만 대답하세요. 한문(한자), 일본어, 러시아어 등 다른 언어를 절대 섞어 쓰지 마세요.
6. 답변은 최소 4 문단 이상, 아주 긴 호흡으로 넉넉하게 작성하세요.
7. HTML이나 마크다운 문법을 활용해 가독성 있게 응답하세요."""
    
    if len(messages) > 0 and messages[0].get('role') != 'system':
        messages.insert(0, {"role": "system", "content": system_prompt})
        
    if len(messages) > 0 and messages[-1].get('role') == 'user':
        messages[-1]['content'] += "\n\n(시스템 제약사항: 분량을 아주 길고 풍부하게 작성하세요. 100% 한글로만 답하세요.)"
        
    success, result_text = _call_gemini_chat(api_key, messages, temperature=0.65)
    
    if not success and ("429" in result_text or "exceeded" in result_text.lower()):
        # Fallback to Groq API if Gemini rate limit is hit
        groq_api_key = os.environ.get('GROQ_API_KEY')
        if groq_api_key:
            success, result_text = _call_groq_chat(groq_api_key, messages, temperature=0.6)
            if success:
                result_text = "💡 (제미나이 사용량 초과로 보조 AI가 답합니다) \n\n" + result_text
    
    if success:
        return jsonify({"success": True, "reply": result_text})
    else:
        return jsonify({"success": False, "error": result_text})

@app.route('/api/shorts/prompts', methods=['POST'])
def generate_shorts_prompts():
    data = request.json
    sentences = data.get('sentences', [])
    if not sentences:
        return jsonify({"success": False, "error": "No sentences provided."})
        
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "[필수] Groq API 키가 없습니다. Render Environment에 GROQ_API_KEY를 등록해주세요."})
        
    import json
    sys_prompt = f"""You are an expert AI image prompt engineer for YouTube Shorts generation. 
I will provide you a JSON array of Korean sentences from a video script. 
For each sentence, translate the core meaning and visual elements into a highly descriptive, aesthetic English prompt that works perfectly for text-to-image AI (like Midjourney or Stable Diffusion). 
The output MUST be a strict, valid JSON array of strings, where each string is the English prompt corresponding to the input sentence. 
Every single prompt MUST include keywords like: 'vertical orientation, 9:16 aspect ratio, masterpiece, highly detailed, high quality, 8k resolution, cinematic lighting'. Do not output any markdown blocks like ```json, just the raw JSON array string. No explanations.

Input sentences (JSON array):
{json.dumps(sentences, ensure_ascii=False)}
"""
    success, text = _call_groq(api_key, sys_prompt)
    if not success:
        return jsonify({"success": False, "error": text})
        
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        english_prompts = json.loads(text)
        return jsonify({"success": True, "prompts": english_prompts})
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to parse LLM response: {str(e)}", "raw_text": text})

@app.route('/api/shorts/export', methods=['POST'])
def export_mp4():
    data = request.json
    script = data.get('script', '')
    images = data.get('images', [])
    bgm_url = data.get('bgm_url', '')
    gender = data.get('gender', 'male')

    if not script or not images:
        return jsonify({'success': False, 'error': '대본과 이미지가 필수입니다.'})

    job_id = uuid.uuid4().hex
    
    # Store initial job state as a file so all Gunicorn workers can access it
    job_file_path = os.path.join(tempfile.gettempdir(), f"job_{job_id}.json")
    with open(job_file_path, "w") as f:
        json.dump({'status': 'processing', 'url': None, 'error': None}, f)
    
    # Run heavy processing in background thread to avoid Gunicorn 30s timeout
    thread = threading.Thread(target=process_export_task, args=(job_id, script, images, bgm_url, gender))
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'job_id': job_id})

@app.route('/api/shorts/status/<job_id>', methods=['GET'])
def export_status(job_id):
    job_file_path = os.path.join(tempfile.gettempdir(), f"job_{job_id}.json")
    if not os.path.exists(job_file_path):
        return jsonify({'status': 'error', 'error': '작업을 찾을 수 없습니다.'})
    
    try:
        with open(job_file_path, "r") as f:
            job = json.load(f)
        return jsonify(job)
    except:
        return jsonify({'status': 'processing'})

def process_export_task(job_id, script, images, bgm_url, gender):
    try:
        temp_dir = tempfile.mkdtemp()
        static_dir = os.path.join(app.root_path, 'static')
        os.makedirs(static_dir, exist_ok=True)
        
        output_filename = f"shorts_{job_id[:8]}.mp4"
        output_path = os.path.join(static_dir, output_filename)
        
        font_path = os.path.join(static_dir, 'NanumGothic.ttf')
        if not os.path.exists(font_path):
            try:
                # Bypass SSL for font download just in case
                urllib.request.urlretrieve("https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf", font_path)
            except Exception as e:
                print(f"Font download failed: {e}")
                
        pil_font = None
        try:
            pil_font = ImageFont.truetype(font_path, 40)
        except:
            pil_font = ImageFont.load_default()

        sentences = [s.strip() for s in re.split(r'[.?!|\n]+', script) if s.strip()]
        if not sentences:
            sentences = ["대본이 없습니다."]

        from moviepy import ImageClip, AudioFileClip, CompositeAudioClip, concatenate_videoclips
        
        # Bypass SSL verification issues on Mac/Linux
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        clips = []
        
        async def generate_edge_audio(text, voice_name, path):
            communicate = edge_tts.Communicate(text, voice_name)
            await communicate.save(path)

        async def generate_all_tts(sentences, voice_model, temp_dir):
            for i, text in enumerate(sentences):
                audio_path = os.path.join(temp_dir, f"audio_{i}.mp3")
                edge_success = False
                last_err = ""
                for attempt in range(3):
                    try:
                        await generate_edge_audio(text, voice_model, audio_path)
                        edge_success = True
                        break
                    except Exception as e:
                        last_err = str(e)
                        await asyncio.sleep(1.0)
                
                if not edge_success:
                    # 마이크로소프트 서버가 3번 다 튕기면 구글 기본 성우(gTTS)로 자동 우회
                    try:
                        from gtts import gTTS
                        tts = gTTS(text=text, lang='ko', timeout=5.0)
                        tts.save(audio_path)
                    except Exception as e2:
                        raise Exception(f"성우 서버 최종 접속 실패. MS({last_err}), 구글({str(e2)})")
                        
                await asyncio.sleep(0.3)
            
        voice_model = 'ko-KR-SunHiNeural' if gender == 'female' else 'ko-KR-InJoonNeural'

        # 1. 순차적으로 모든 TTS 생성 (이미지는 아래에서 병렬 다운로드 유지)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(generate_all_tts(sentences, voice_model, temp_dir))

        # 2. 병렬로 모든 고해상도 이미지 다운로드
        def fetch_image(img_src):
            if img_src.startswith('data:image'):
                header, encoded = img_src.split(',', 1)
                return base64.b64decode(encoded)
            else:
                req = urllib.request.Request(img_src, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=15.0) as response:
                    return response.read()

        import concurrent.futures
        unique_images_data = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_src = {executor.submit(fetch_image, src): src for src in set(images)}
            for future in concurrent.futures.as_completed(future_to_src):
                src = future_to_src[future]
                unique_images_data[src] = future.result()

        for i, text in enumerate(sentences):
            audio_path = os.path.join(temp_dir, f"audio_{i}.mp3")
            audio_clip = AudioFileClip(audio_path)
            duration = audio_clip.duration
            if duration < 1.0: duration = 1.0 

            img_idx = math.floor((i / len(sentences)) * len(images))
            safe_img_idx = min(img_idx, len(images) - 1)
            img_src = images[safe_img_idx]

            img_file_path = os.path.join(temp_dir, f"img_{i}_{safe_img_idx}.png")
            
            img_data = unique_images_data.get(img_src)
            pil_img = PILImage.open(BytesIO(img_data)).convert('RGB')

            target_w, target_h = 720, 1280
            w, h = pil_img.size
            if w/h > target_w/target_h:
                new_w = int(h * target_w/target_h)
                offset = (w - new_w) // 2
                pil_img = pil_img.crop((offset, 0, offset + new_w, h))
            else:
                new_h = int(w * target_h/target_w)
                offset = (h - new_h) // 2
                pil_img = pil_img.crop((0, offset, w, offset + new_h))
            
            # 랜초스 필터 대신 가볍고 빠른 바이리니어 필터 적용
            pil_img = pil_img.resize((target_w, target_h), PILImage.Resampling.BILINEAR)
            
            draw = ImageDraw.Draw(pil_img)
            words = text.split()
            lines = []
            curr_line = []
            for w in words:
                curr_line.append(w)
                if len(" ".join(curr_line)) > 15:
                    lines.append(" ".join(curr_line))
                    curr_line = []
            if curr_line: lines.append(" ".join(curr_line))
            
            # 여기서 문자열로 된 '\\n'이 아니라 실제 개행 문자 '\n'을 사용해야 줄바꿈이 됩니다.
            text_str = "\n".join(lines)
            
            bbox = draw.multiline_textbbox((0, 0), text_str, font=pil_font, align="center")
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (target_w - text_w) / 2
            y = target_h - text_h - 150
            
            draw.rectangle([x-20, y-20, x+text_w+20, y+text_h+20], fill=(0,0,0,180))
            draw.multiline_text((x, y), text_str, font=pil_font, fill=(255,255,255), align="center")
            
            pil_img.save(img_file_path)
            
            vclip = ImageClip(img_file_path).with_duration(duration)
            vclip = vclip.with_audio(audio_clip)
            clips.append(vclip)

        # method="chain"으로 변경하여 CompositeVideoClip 빌드 시 발생하는 막대한 메모리(RAM) 피크 및 OOM 킬 방지
        final_video = concatenate_videoclips(clips, method="chain")

        final_audio = final_video.audio
        if bgm_url:
            bgm_path = os.path.join(temp_dir, "bgm.mp3")
            if bgm_url.startswith('data:audio'):
                header, encoded = bgm_url.split(',', 1)
                with open(bgm_path, "wb") as f:
                    f.write(base64.b64decode(encoded))
            else:
                req = urllib.request.Request(bgm_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=15.0) as response:
                    with open(bgm_path, "wb") as f:
                        f.write(response.read())
            
            bgm_clip = AudioFileClip(bgm_path)
            from moviepy.audio.fx import MultiplyVolume
            bgm_clip = bgm_clip.with_effects([MultiplyVolume(0.15)])
            # MP3 파일 헤더 문제로 duration이 너무 짧게 인식(예: 0.01초)되어 AudioLoop이 수백만 개의 클립을 생성해 메모리가 다운되는 것을 방지합니다.
            if getattr(bgm_clip, 'duration', 0) is None or bgm_clip.duration < 1.0:
                bgm_clip = bgm_clip.with_duration(final_video.duration)
            else:
                from moviepy.audio.fx import AudioLoop
                if bgm_clip.duration < final_video.duration:
                    bgm_clip = bgm_clip.with_effects([AudioLoop(duration=final_video.duration)])
                else:
                    bgm_clip = bgm_clip.subclipped(0, final_video.duration)
                
            final_audio = CompositeAudioClip([final_audio, bgm_clip])
            final_video = final_video.with_audio(final_audio)

        final_video.write_videofile(
            output_path, 
            fps=15, 
            codec="libx264", 
            audio_codec="aac", 
            preset="ultrafast", 
            threads=1, 
            logger=None
        )
        
        final_video.close()
        for c in clips:
            c.close()

        job_file_path = os.path.join(tempfile.gettempdir(), f"job_{job_id}.json")
        with open(job_file_path, "w") as f:
            json.dump({'status': 'completed', 'url': f"/static/{output_filename}", 'error': None}, f)

    except Exception as e:
        traceback.print_exc()
        job_file_path = os.path.join(tempfile.gettempdir(), f"job_{job_id}.json")
        with open(job_file_path, "w") as f:
            json.dump({'status': 'error', 'url': None, 'error': str(e)}, f)

@app.route('/api/restaurant/search', methods=['POST'])
def restaurant_search():
    data = request.json
    address = data.get('address', '').strip()
    radius = int(data.get('radius', 5000))
    
    api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "서비스 설정 오류: 카카오 REST API 키가 환경 변수에 등록되지 않았습니다."})
        
    if not address:
        return jsonify({"success": False, "error": "주소를 입력해주세요."})
        
    headers = {"Authorization": f"KakaoAK {api_key}"}
    
    # 1. 주소 -> 위경도 변환
    geo_url = f"https://dapi.kakao.com/v2/local/search/address.json?query={urllib.parse.quote(address)}"
    try:
        geo_resp = requests.get(geo_url, headers=headers)
        geo_data = geo_resp.json()
        
        # 주소 검색 실패시 키워드 장소 검색으로 fallback (예: "대명로 256", "스타벅스 강남점" 등)
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

@app.route("/api/geocode", methods=["POST"])
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

@app.route("/api/restaurant/summary", methods=["POST"])
def restaurant_summary():
    try:
        data = request.json or {}
        place_id = data.get("place_id")
        place_type = data.get("place_type", "맛집")
        import os
        google_api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
        
        if not place_id or not google_api_key:
            return jsonify({"success": False, "error": "요청 정보가 올바르지 않거나 구글 API 키가 세팅되지 않았습니다."})
            
        det_url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=reviews&language=ko&key={google_api_key}"
        import requests
        resp = requests.get(det_url).json()
        reviews = resp.get("result", {}).get("reviews", [])
        
        if not reviews:
            return jsonify({"success": True, "summary": "아직 리뷰가 충분하지 않아 요약할 수 없습니다."})
            
        review_texts = [r.get("text") for r in reviews if r.get("text")]
        combined_text = "\n".join(review_texts[:5])
        
        if not combined_text.strip():
            return jsonify({"success": True, "summary": "아직 텍스트 리뷰가 없어 요약할 수 없습니다."})
            
        import os
        groq_api_key = os.environ.get("GROQ_API_KEY")
        gemini_api_key = os.environ.get("GEMINI_API_KEY")
        
        if not groq_api_key and not gemini_api_key:
            return jsonify({"success": False, "error": "AI API 키(Groq 또는 Gemini)가 세팅되지 않았습니다."})
            
        if place_type == "빵집":
            prompt = f"""다음은 특정 빵집/베이커리의 실제 리뷰 5개입니다.
이 리뷰들을 종합해서 다음 두 가지 항목을 작성해주세요:
1. 🤖 핵심 요약 (2줄 이내): 빵의 맛, 분위기, 주차 여부 등 가장 핵심적이고 유용한 점.
2. 👑 꼭 사야하는 빵: 리뷰어들이 가장 많이 극찬하는 시그니처 빵 이름. (없으면 '알 수 없음' 이라고 표기)

[리뷰 데이터]:
{combined_text}
"""
        elif place_type == "카페":
            prompt = f"""다음은 특정 카페의 실제 리뷰 5개입니다.
이 리뷰들을 종합해서 다음 두 가지 항목을 작성해주세요:
1. 🤖 핵심 요약 (2줄 이내): 커피의 맛, 감성/뷰, 작업(카공) 또는 데이트 분위기 등 가장 핵심적이고 유용한 점.
2. ☕ 시그니처 메뉴: 리뷰어들이 가장 많이 극찬하는 커피나 디저트 등. (없으면 '알 수 없음' 표기)

[리뷰 데이터]:
{combined_text}
"""
        elif place_type == "병원":
            prompt = f"""다음은 특정 병원/클리닉의 실제 리뷰 5개입니다.
이 리뷰들을 종합해서 다음 두 가지 항목을 작성해주세요:
1. 🤖 핵심 요약 (2줄 이내): 의사 선생님의 친절도, 진료 퀄리티, 대기 시간 길이 등 가장 핵심적인 내용.
2. 🏥 상세 정보: 과잉 진료 여부나 리뷰어들이 유독 강조하는 장단점 피드백. (알 수 없으면 '알 수 없음' 표기)

[리뷰 데이터]:
{combined_text}
"""
        else:
            prompt = f"""다음은 특정 맛집의 실제 리뷰 5개입니다.
이 리뷰들을 종합해서 가장 핵심적이고 유용한 점(맛, 분위기, 주차, 서비스 등)을 바탕으로, 친근하고 생동감 있는 2~3줄 길이의 짧은 조언(요약)을 봇처럼 작성해주세요. 

[리뷰 데이터]:
{combined_text}
"""
        
        # 1. 빠른 Groq API 우선 시도
        if groq_api_key:
            sys_role = "당신은 리뷰를 전문적으로 요약해주는 친절한 한국인 AI 점원입니다. 반드시 자연스러운 한국어 문장으로만 대답하세요. 외계어나 한자, 베트남어, 러시아어 등 이상한 글자가 섞이면 절대 안 됩니다."
            success, text = _call_groq(groq_api_key, prompt, system_role=sys_role)
            if success:
                return jsonify({"success": True, "summary": text})
            else:
                if not gemini_api_key:
                    return jsonify({"success": False, "error": f"Groq 통신 실패: {text}"})

        # 2. Gemini fallback (Groq 키가 없거나 실패한 경우)
        import google.generativeai as genai
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        response = model.generate_content(prompt)
        return jsonify({"success": True, "summary": response.text.strip()})
        
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print("===== [AI SUMMARY ERROR] =====")
        print(err_msg)
        error_str = str(e)
        if "429" in error_str or "quota" in error_str.lower() or "exceeded" in error_str.lower():
            return jsonify({"success": False, "error": "AI 호출 한도 초과: 구글 제미나이 무료 제공량(1분 15회)이 초과되었습니다. 잠시 후 다시 시도해주세요."})
        return jsonify({"success": False, "error": f"AI 분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요. ({error_str})" })

@app.route("/api/restaurant/chat", methods=["POST"])
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
        
        response = model.generate_content(prompt)
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

@app.route('/bakery')
def bakery():
    return render_template('bakery.html')

@app.route('/api/bakery/search', methods=['POST'])
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

@app.route('/cafe')
def cafe():
    return render_template('cafe.html')

@app.route('/api/cafe/search', methods=['POST'])
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

@app.route('/clinic')
def clinic():
    return render_template('clinic.html')

@app.route('/api/clinic/search', methods=['POST'])
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

@app.route('/api/shorts/script/ask', methods=['POST'])
def shorts_script_ask():
    data = request.json
    idea = data.get('idea', '')
    history = data.get('history', [])
    q_index = data.get('questionIndex', 1)
    
    if not idea:
        return jsonify({"success": False, "error": "아이디어를 입력해주세요."})
        
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "GROQ_API_KEY가 없습니다."})
        
    try:
        history_text = "\n".join([f"Q: {item['question']}\nA: {item['answer']}" for item in history]) if history else "없음"
            
        sys_prompt = f"""당신은 100만 유튜버를 기획하는 쇼츠(Shorts) 전문 PD이자 스크립트 라이터입니다.
초기 기획: "{idea}"
지금까지 진행된 문답:
{history_text}

이 쇼츠를 가장 흥미롭고 자극적(몰입감 있게)으로 구성하기 위해, 사용자에게 물어봐야 할 **과감한 질문 단 하나**를 생성하세요. 
이 질문은 {q_index}번째 질문입니다. (총 5개의 질문 예정)
사용자가 쉽게 고를 수 있도록 흥미로운 **객관식 선택지 3~4개**를 함께 제공해야 합니다.

반드시 아래 JSON 형식으로만 응답해야 합니다. 다른 말은 절대 추가하지 마세요.
{{
  "question": "핵심 질문 내용...",
  "options": ["매우 자극적인 도입부", "감성적인 스토리텔링", "핵심만 빠르게 전달"] 
}}"""
        success, text = _call_groq(api_key, sys_prompt)
        
        if not success:
            return jsonify({"success": False, "error": f"통신 실패: {text}"})
            
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        import json
        q_data = json.loads(text)
        return jsonify({"success": True, "question": q_data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/shorts/script/generate', methods=['POST'])
def shorts_script_generate():
    data = request.json
    idea = data.get('idea', '')
    answers = data.get('answers', [])
    
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "GROQ_API_KEY가 없습니다."})
        
    try:
        if not answers:
            return jsonify({"success": False, "error": "문답 기록이 부족합니다."})
            
        history_text = "\n".join([f"Q: {ans['question']}\nA: {ans['answer']}" for ans in answers])
        
        sys_prompt = f"""당신은 100만 구독자를 지닌 천재 쇼츠 기획출신 유튜버입니다. 
당신의 임무는 아래 [유저의 기획안]과 [진행된 5번의 심층 문답]을 모두 종합하여, 유튜브 쇼츠(Shorts) 영상에서 성우가 직접 읽을 **'나레이션 대본 텍스트'**만을 완성해서 출력하는 것입니다.

[기획안]
{idea}

[심층 문답]
{history_text}

[🚨 대본 작성 5대 절대 규칙 🚨]
1. 절대로 질문을 다시 하거나, 사용자에게 피드백을 요구하지 마세요. 당신의 유일한 임무는 '완성된 대본 텍스트'를 출력하는 것입니다.
2. 대본은 반드시 영상에 들어갈 순수 나레이션/자막 텍스트로만 100% 구성되어야 합니다. 시각적 효과 코멘트(예: [화면 전환], [음악 재생])나 지문(가로치고 적는 행동 묘사)을 절대로 적지 마세요.
3. 숏폼 특성에 맞게 도입부(Hook)는 아주 강렬하고 빠르게 시작하세요.
4. 문장은 성우 AI(TTS)가 자연스럽게 숨을 쉬며 읽을 수 있도록 마침표(.)나 느낌표(!)로 짧고 명확하게 끊어주세요.
5. 오직 대본 문자열만 처음부터 끝까지 연속으로 출력하세요. 당신의 인사말, 서론 설명, 부가 코멘트, '제목 제안' 등을 절대로 붙이지 마세요.

위 내용을 바탕으로 도파민이 터지는 60초 분량(문자수 약 300자~450자)의 '최고의 나레이션 대본'을 즉시 작성하세요."""
        
        # 제미나이 엔진 기반 대본 생성 (지시사항 이행 능력이 훨씬 좋음)
        gemini_key = os.environ.get('GEMINI_API_KEY')
        if gemini_key:
            success, text = _call_gemini_chat(gemini_key, [{"role": "user", "content": sys_prompt}], temperature=0.7)
            # 할당량 초과 시 Groq으로 자동 우회
            if not success and ("429" in text or "exceeded" in text.lower()):
                success, text = _call_groq(api_key, sys_prompt)
        else:
            success, text = _call_groq(api_key, sys_prompt)
        if success:
            return jsonify({"success": True, "script": text})
        else:
            return jsonify({"success": False, "error": text})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/game_office')
def game_office():
    return render_template('game_office.html')

if __name__ == '__main__':
    # When hosted on Render, Gunicorn parses the app instance. 
    # This block is for simple local testing via `python main.py`
    import os
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port, debug=False)
