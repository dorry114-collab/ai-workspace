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
                'open': float(row['Open']) if ('Open' in row and not pd.isna(row['Open'])) else c_val,
                'high': float(row['High']) if ('High' in row and not pd.isna(row['High'])) else c_val,
                'low': float(row['Low']) if ('Low' in row and not pd.isna(row['Low'])) else c_val,
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
        if len(recent_data) > 30 and os.environ.get('GEMINI_API_KEY'):
            api_key = os.environ.get('GEMINI_API_KEY')
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
            
            p_prompt = f"""당신은 냉철하고 분석력이 뛰어난 월스트리트의 탑 티어 주식 애널리스트입니다. 오직 100% 자연스러운 한국어(Korean)로만 대답하세요.

종목: {ticker} ({raw_ticker})
현재가: {current_p:.2f}
최근 1개월 최고가: {high_1m:.2f} / 최저가: {low_1m:.2f}
장기 평균 가격선(SMA 50): {sma50_str}
시장 과열점수(RSI): {rsi_str} (70 이상은 위험, 30 이하는 안전)
볼린저 밴드 상단: {bb_upper_str} / 하단: {bb_lower_str}
MACD: {macd_str} (시그널 {macd_sig_str})
최근 거래량: {vol_trend_str} (평소 대비 {vol_ratio:.1f}%)

위 기술적 지표들을 종합하여, 현재 주가 흐름에 대한 날카롭고 전문적인 차트 분석을 제공해 주세요. 
🔥 **[중요 필수 지침]** 분석글을 작성할 때 반드시 뭉뚱그려 말하지 말고, "현재가 82,000원은 볼린저 밴드 상단인 83,000원에 근접해 있으며...", "RSI 지수가 75.3으로 과열 구간에 진입하여..." 와 같이 제공된 **'정확한 수치'**와 **'전문 명칭(SMA, RSI, MACD 등)'**을 텍스트 문장 안에 직접적으로 빵빵하게 포함하여 작성하세요.
단, 초보자도 쉽게 이해할 수 있도록 어려운 전문 용어가 쓰인 분석글 하단에는 '용어 해설표'를 반드시 별도로 마련하여 짧고 명확하게 뜻을 풀이해 주세요.

반드시 아래 JSON 형식으로만 응답해야 합니다.
{{
  "analysis": "제공된 가격 수치와 지표 명칭(RSI, MACD 등)을 적극적으로 본문에 인용하여 작성한 5~7문장 분량의 전문가적 차트 분석. (단, 문단이 구분되도록 확실하게 줄바꿈 문자를 넣고, 본문 끝에는 빈 줄을 넣은 뒤 '\\n\\n---\\n[용어 해설]\\n- MACD: ...\\n- RSI: ...' 형태로 가독성을 극대화하여 덧붙일 것)",
  "target_price": 1개월 뒤 합리적인 목표가격(숫자만 입력),
  "stop_loss": 손절매(위험관리) 목표 가격(숫자만 입력)
}}"""
            try:
                sys_role = "당신은 냉철하고 전문적인 주식 애널리스트입니다. 구체적인 데이터 수치와 지표명을 본문에 직접 언급하며 깊이 있게 분석하되, 어려운 용어는 하단에 쉽게 풀이해줍니다."
                messages = [
                    {"role": "system", "content": sys_role},
                    {"role": "user", "content": p_prompt}
                ]
                success, text = _call_gemini_chat(api_key, messages, temperature=0.5)
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
    gemini_api_key = os.environ.get('GEMINI_API_KEY')
    groq_api_key = os.environ.get('GROQ_API_KEY')
    if not gemini_api_key and not groq_api_key:
        return jsonify({"success": False, "error": "[필수] API 키가 없습니다. Render Environment에 API_KEY를 등록해주세요."})
        
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
        
        # 엔진 이중화: 제미나이 우선, 한도 초과 시 Groq으로 폴백
        success = False
        text = ""
        if gemini_api_key:
            success, text = _call_gemini_chat(gemini_api_key, [{"role": "user", "content": sys_prompt}], temperature=0.7)
            if not success and ("429" in text or "exceeded" in text.lower()) and groq_api_key:
                success, text = _call_groq(groq_api_key, sys_prompt)
        elif groq_api_key:
            success, text = _call_groq(groq_api_key, sys_prompt)
        
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
    gemini_api_key = os.environ.get('GEMINI_API_KEY')
    groq_api_key = os.environ.get('GROQ_API_KEY')
    if not gemini_api_key and not groq_api_key:
        return jsonify({"success": False, "error": "API 키가 없습니다."})
        
    try:
        answers_text = "\n".join([f"Q: {a['question']}\nA: {a['answer']}" for a in answers])
        
        sys_prompt = f"""초기 아이디어: {idea}

사용자의 추가 답변:
{answers_text}

위 내용을 바탕으로 사용자가 ChatGPT나 Claude 등에 그대로 복사해서 붙여넣기만 하면 최고의 결과가 나올 수 있는 '궁극의 마스터 프롬프트'를 마크다운 형태의 코드 블록(```) 영역 안에 작성해주세요.
[역할 지정], [구체적 목적], [세부 규칙], [출력 양식] 등 최신 프롬프트 가이드라인을 잘 지켜서 풍성하고 디테일하게 오직 100% 한국어로만 작성해주세요."""

        success = False
        final_text = ""
        if gemini_api_key:
            success, final_text = _call_gemini_chat(gemini_api_key, [{"role": "user", "content": sys_prompt}], temperature=0.7)
            if not success and ("429" in final_text or "exceeded" in final_text.lower()) and groq_api_key:
                success, final_text = _call_groq(groq_api_key, sys_prompt)
        elif groq_api_key:
            success, final_text = _call_groq(groq_api_key, sys_prompt)
        
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

@app.route('/youtube_summary')
def youtube_summary():
    return render_template('youtube_summary.html')

@app.route('/api/youtube/summary', methods=['POST'])
def api_youtube_summary():
    data = request.json
    video_url = data.get('url', '').strip()
    
    if not video_url:
        return jsonify({"success": False, "error": "유튜브 웹 주소를 입력해주세요."})
        
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "GEMINI_API_KEY가 없습니다."})
        
    import re
    # Extract video ID from URL
    # Matches: v=XXXX, or youtu.be/XXXX
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", video_url)
    if not match:
        return jsonify({"success": False, "error": "유효하지 않은 유튜브 URL입니다."})
        
    video_id = match.group(1)
    
    from youtube_transcript_api import YouTubeTranscriptApi
    import google.generativeai as genai
    import tempfile, glob, subprocess, time
    
    transcript_available = False
    full_transcript = ""
    audio_file_path = None
    genai_file = None
    result_text = ""
    
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        transcript = transcript_list.find_transcript(['ko', 'en'])
        t_data = transcript.fetch()
        
        transcript_text = []
        for t in t_data:
            start_sec = int(getattr(t, 'start', 0) if not isinstance(t, dict) else t.get('start', 0))
            text_content = getattr(t, 'text', '') if not isinstance(t, dict) else t.get('text', '')
            m, s = divmod(start_sec, 60)
            time_str = f"[{m:02d}:{s:02d}]"
            transcript_text.append(f"{time_str} {text_content}")
        full_transcript = " ".join(transcript_text)
        transcript_available = True
    except Exception as e:
        transcript_available = False
        
    p_prompt_tail = """
위 내용을 바탕으로 다음 정보를 작성해주세요. 전문 용어는 초보자 기준 일상 비유로 풀어서, Mermaid 차트는 아주 심플한 graph TD 구조로만 작성하세요. 반드시 JSON 형식으로만 응답해야 합니다.

{
  "sentiment_emoji": "영상 전반의 분위기를 나타내는 이모지 1개 (예: ☀️, 🌋, 🌩️, 📚, 💡)",
  "sentiment_label": "분위기 한줄 요약 (예: 열정적이고 공격적인 경고)",
  "core_summary": "영상에 등장한 구체적인 명칭(기업명, 인물, 지표 등)과 핵심 수치/결과를 꽉꽉 채워 넣어, 누구나 단숨에 뼈대를 이해할 수 있도록 날카롭고 명확하게 작성한 '초핵심 요약' (정확히 5문장)",
  "timeline_summary": [
    { "time": "12:34", "sec": 754, "title": "구간 핵심 주제", "desc": "해당 구간에서 언급된 중요 단어나 숫자를 포함한 구체적인 구간 요약" }
  ],
  "summary": "영상에서 화자가 언급한 구체적인 데이터(수치, 통계), 고유 명사, 전문 용어, 구체적 사례들을 하나도 빠짐없이 포함하여 깊이 있게 작성하되, 단순히 줄글로 길게 늘어놓지 마세요. 대주제-중주제-소주제의 계층 구조가 명확히 보이도록 '1. 대분류', '1) 중분류', '(1) 소분류', 'a. 세부사항' 과 같이 체계적인 번호와 기호를 매겨서 한눈에 들어오는 가독성 높은 구조적인 요약을 작성하세요.",
  "suggested_questions": [
    "시청자가 본문의 구체적인 수치나 주장에 대해 AI에게 심층적으로 물어볼 만한 날카로운 질문 예시 1",
    "질문 예시 2",
    "질문 예시 3"
  ],
  "glossary": [
    { "term": "영상에 등장한 구체적인 어려운 용어 1", "explanation": "초보자를 위해 일상생활 예시를 곁들인 쉬운 뜻풀이" }
  ],
  "mermaid_code": "graph TD\\n  A[\\"최상단 제목\\"] --> B[\\"주장 1\\"]\\n  A --> C[\\"주장 2\\"] 처럼 작성. 노드 괄호 안에는 반드시 큰따옴표(\\")를 써서 특수문자 오류를 방지하세요. 줄바꿈 문법(\\\\n)을 사용한 순수 텍스트열로 응답."
}"""

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        if transcript_available:
            p_prompt = f"다음은 유튜브 영상의 텍스트 스크립트(타임스탬프 포함)입니다:\n{full_transcript[:25000]}\n" + p_prompt_tail
            response = model.generate_content(p_prompt, generation_config=genai.types.GenerationConfig(temperature=0.7))
            result_text = response.text
        else:
            # Fallback to audio download
            temp_dir = tempfile.gettempdir()
            audio_base_path = os.path.join(temp_dir, f"yt_audio_{video_id}")
            import sys
            # Clean URL to avoid yt-dlp parsing errrors from parameters like '?si='
            clean_url = f"https://www.youtube.com/watch?v={video_id}"
            # yt-dlp download (audio only) via python module to avoid path issues
            dl_result = subprocess.run([sys.executable, '-m', 'yt_dlp', '-f', 'bestaudio', '-x', '--audio-format', 'mp3', '-o', f'{audio_base_path}.%(ext)s', clean_url], capture_output=True, text=True)
            
            if dl_result.returncode == 0:
                # find the downloaded mp3
                audio_files = glob.glob(f"{audio_base_path}.*")
                if not audio_files:
                    raise Exception("오디오 파일 다운로드에 실패했습니다.")
                audio_file_path = audio_files[0]
                
                # Upload to gemini
                genai_file = genai.upload_file(audio_file_path, mime_type="audio/mp3")
                while genai_file.state.name == 'PROCESSING':
                    time.sleep(2)
                    genai_file = genai.get_file(genai_file.name)
                    if genai_file.state.name == 'FAILED':
                        raise Exception("제미나이 오디오 분석 처리에 실패했습니다.")
                
                p_prompt = "다음은 자막이 제공되지 않는 유튜브 영상의 원본 오디오 파일입니다. 오디오를 직접 청취하고 내용을 이해해주세요.\n" + p_prompt_tail
                response = model.generate_content([genai_file, p_prompt], generation_config=genai.types.GenerationConfig(temperature=0.7))
                result_text = response.text
                full_transcript = "(해당 영상은 자막이 제공되지 않아, AI가 원본 오디오를 직접 청취하여 분석한 결과입니다.)"
            else:
                # Youtube Bot Blocked -> Fallback to parsing Title and Author using Official oEmbed API
                import requests
                
                oembed_url = f"https://www.youtube.com/oembed?url={clean_url}&format=json"
                try:
                    req_response = requests.get(oembed_url, timeout=10)
                    if req_response.status_code == 200:
                        data = req_response.json()
                        title_text = data.get('title', '제목 알 수 없음')
                        author_name = data.get('author_name', '채널 알 수 없음')
                        
                        p_prompt = f"[안내] 유튜브 서버 차단(Render IP Bot Block) 등으로 대본과 오디오 추출에 모두 실패했습니다.\n다만 공식 API를 통해 알아낸 다음 정보만을 바탕으로 핵심 주제를 유추해서 가상의 요약본을 작성해 주세요:\n\n영상 제목: {title_text}\n채널 이름: {author_name}\n\n" + p_prompt_tail
                        response = model.generate_content(p_prompt, generation_config=genai.types.GenerationConfig(temperature=0.7))
                        result_text = response.text
                        full_transcript = "(해당 영상은 서버 IP 차단으로 대본을 가져오지 못해, 불가피하게 '영상 제목'과 '채널명'만을 토대로 AI가 제한적으로 유추한 기사입니다.)"
                        transcript_available = False
                    else:
                        raise Exception("oEmbed API도 실패했습니다.")
                except Exception as ex:
                    raise Exception(f"유튜브 서버가 이 서버의 접근을 완전히 차단했습니다. (IP Blocked) - {str(ex)}")
    except Exception as e:
        return jsonify({"success": False, "error": f"AI 분석 중 오류 발생: {str(e)}"})
    finally:
        if genai_file:
            try:
                genai.delete_file(genai_file.name)
            except:
                pass
        if audio_file_path and os.path.exists(audio_file_path):
            try:
                os.remove(audio_file_path)
            except:
                pass

    if "```json" in result_text: result_text = result_text.split("```json")[1].split("```")[0].strip()
    elif "```" in result_text: result_text = result_text.split("```")[1].split("```")[0].strip()
    
    import json
    try:
        ai_data = json.loads(result_text)
    except json.JSONDecodeError:
        return jsonify({"success": False, "error": "AI가 올바른 JSON 데이터를 반환하지 않았습니다."})
        
    return jsonify({
                "success": True,
                "video_id": video_id,
                "sentiment_emoji": ai_data.get('sentiment_emoji', '💡'),
                "sentiment_label": ai_data.get('sentiment_label', '중립적 정보 전달'),
                "core_summary": ai_data.get('core_summary', ''),
                "timeline_summary": ai_data.get('timeline_summary', []),
                "summary": ai_data.get('summary', '요약 실패'),
                "suggested_questions": ai_data.get('suggested_questions', []),
                "glossary": ai_data.get('glossary', []),
                "mermaid_code": ai_data.get('mermaid_code', ''),
                "full_transcript": full_transcript,
                "is_fallback": not transcript_available
            })


@app.route('/api/youtube/chat', methods=['POST'])
def api_youtube_chat():
    data = request.json
    video_id = data.get('video_id', '')
    prompt = data.get('prompt', '')
    
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "GEMINI_API_KEY가 설정되지 않았습니다."})
        
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        transcript = transcript_list.find_transcript(['ko', 'en'])
        t_data = transcript.fetch()
        full_transcript = " ".join([getattr(t, 'text', '') if not isinstance(t, dict) else t.get('text', '') for t in t_data])
        sys_role = f"""이 사용자는 유튜브 영상을 시청 중이며, 당신은 이 영상과 관련된 질의응답을 수행하는 챗봇입니다.
다음은 영상의 텍스트 스크립트입니다:
{full_transcript[:15000]}
위 내용을 바탕으로 사용자의 질문에 친절하고 정확하게 답해주세요. 영상에 나오지 않은 내용이라면 영상에서 확인할 수 없다고 명확히 답하세요."""
    except Exception:
        sys_role = """이 사용자는 유튜브 영상을 시청 중이며, 당신은 이 영상과 관련된 질의응답을 수행하는 챗봇입니다.
현재 시스템 문제나 봇 차단으로 인해 영상의 구체적인 '자막 대본(Transcript)'을 가져오지 못했습니다. 
따라서 사용자가 영상 내용이나 관련된 주제에 대해 질문하면, 당신이 가지고 있는 '일반적인 지식과 방대한 웹 상식'을 총동원하여 최대한 친절하고 상세하게 답변해 주세요. "영상을 못 봐서 대답할 수 없다"는 식의 거절은 피하고, 최대한 지식을 활용해 유익한 대화를 이어나가세요."""
    
    messages = [
        {"role": "system", "content": sys_role},
        {"role": "user", "content": prompt}
    ]
    
    success, result_text = _call_gemini_chat(api_key, messages, temperature=0.7)
    if success:
        return jsonify({"success": True, "reply": result_text})
    else:
        return jsonify({"success": False, "error": result_text})

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
    
    # Parse query parameters for custom mix
    try:
        hot_cnt = int(request.args.get('hot', 3))
        cold_cnt = int(request.args.get('cold', 3))
    except ValueError:
        hot_cnt, cold_cnt = 3, 3
        
    if hot_cnt + cold_cnt > 6:
        return jsonify({"success": False, "error": "HOT과 COLD 개수의 합은 6을 넘을 수 없습니다."})

    # 역대 가장 많이 나온 10개 번호 (최근까지의 누적 통계 기준)
    top_10 = [34, 43, 12, 27, 1, 13, 17, 39, 33, 18]
    # 역대 가장 적게 나온 10개 번호
    bottom_10 = [9, 22, 29, 23, 28, 8, 30, 32, 42, 25]
    
    # 나머지 번호 풀 계산
    used_numbers = set(top_10 + bottom_10)
    remaining_pool = [i for i in range(1, 46) if i not in used_numbers]
    
    # 상위 10개에서 6개 뽑기 5조합
    top_combs = []
    for _ in range(5):
        top_combs.append(sorted(random.sample(top_10, 6)))
        
    # 하위 10개에서 6개 뽑기 5조합
    bottom_combs = []
    for _ in range(5):
        bottom_combs.append(sorted(random.sample(bottom_10, 6)))
        
    # 커스텀 비율로 섞기 (MIX) 5조합
    mixed_combs = []
    random_cnt = 6 - (hot_cnt + cold_cnt)
    for _ in range(5):
        mixed = []
        if hot_cnt > 0: mixed.extend(random.sample(top_10, hot_cnt))
        if cold_cnt > 0: mixed.extend(random.sample(bottom_10, cold_cnt))
        if random_cnt > 0: mixed.extend(random.sample(remaining_pool, random_cnt))
        mixed_combs.append(sorted(mixed))
        
    return jsonify({
        "success": True,
        "top_10_pool": top_10,
        "bottom_10_pool": bottom_10,
        "top_combinations": top_combs,
        "bottom_combinations": bottom_combs,
        "mixed_combinations": mixed_combs
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
        
    system_prompt = """당신은 TRPG 게임의 마스터이자, 사용자와 상호작용하며 흥미진진한 소설을 이끌어가는 뛰어난 작가입니다. 
다음 규칙을 반드시 지켜주세요:
1. 분량을 풍부하게 작성하세요. 매 턴마다 최소 3~4개의 밀도 있는 문단(최소 500자 이상)으로 몰입감 넘치는 묘사와 스토리 진행을 해주세요. (내용이 너무 적으면 안 됩니다).
2. 동일한 단어나 비슷한 문장을 절대 반복하지 마세요. (예: '그는 ~했다. 그는 ~했다.' 식의 반복 금지)
3. 항상 [새로운 사건 발생], [새로운 단서 발견], [새로운 인물 등장] 중 하나를 통해 스토리를 빠르게 앞으로 전진시키세요.
4. 당신의 출력 마지막에는 옛날 TV 예능 '인생극장 (그래 결심했어!)' 처럼 주인공이 직면한 **명확하고 극단적인 두 가지 갈림길(A or B, O or X 형태)**을 제공해야 합니다.
5. 선택지는 반드시 다음과 같은 정확한 텍스트 형식으로 맨 마지막 줄에 작성하세요:
[선택 A] (가장 첫 번째 운명의 선택 행동 묘사)
[선택 B] (완전히 반대되거나 다른 방향의 운명의 선택 행동 묘사)
6. 반드시 자연스럽고 매끄러운 100% 한국어(Korean)로 대답하세요.
7. HTML이나 마크다운 문법을 활용해 문단 구분을 확실하게 하여 가독성을 높이세요."""
    
    if len(messages) > 0 and messages[0].get('role') != 'system':
        messages.insert(0, {"role": "system", "content": system_prompt})
        
    if len(messages) > 0 and messages[-1].get('role') == 'user':
        messages[-1]['content'] += "\n\n(시스템 제약사항: 절대로 방금 전 문장을 반복하지 말고, 즉각적으로 스토리를 다음 단계로 전진시키세요. 엄청나게 구체적이고 긴 분량(최소 3문단)의 소설을 작성하세요. 맨 마지막에는 반드시 '[선택 A] ... [선택 B] ...' 형식으로 정확히 2개의 극단적인 선택지만 주세요.)"
        
    success, result_text = _call_gemini_chat(api_key, messages, temperature=0.85)
    
    if not success and ("429" in result_text or "exceeded" in result_text.lower()):
        # Fallback to Groq API if Gemini rate limit is hit
        groq_api_key = os.environ.get('GROQ_API_KEY')
        if groq_api_key:
            success, result_text = _call_groq_chat(groq_api_key, messages, temperature=0.8)
            if success:
                result_text = "💡 (제미나이 사용량 초과로 보조 AI가 답합니다) \n\n" + result_text
    
    if success:
        return jsonify({"success": True, "reply": result_text})
    else:
        return jsonify({"success": False, "error": result_text})

# --- ENGLISH TUTOR LOGIC ---
@app.route('/english')
def english_tutor():
    return render_template('english_tutor.html')

@app.route('/api/english/chat', methods=['POST'])
def api_english_chat():
    data = request.json
    messages = data.get('messages', [])
    
    gemini_api_key = os.environ.get('GEMINI_API_KEY')
    groq_api_key = os.environ.get('GROQ_API_KEY')
    if not gemini_api_key and not groq_api_key:
        return jsonify({"success": False, "error": "[필수] API 키가 없습니다."})
        
    if not messages:
        return jsonify({"success": False, "error": "메시지 내역이 없습니다."})
        
    system_prompt = """You are an interactive AI English Tutor playing a role in a conversational roleplay.
Your job is to strictly adhere to the following rules:
1. Always output ONLY valid JSON format. Do not use Markdown JSON wrappers like ```json.
2. Evaluate the user's latest English message (unless this is the very first turn to start the conversation).
3. If this is the start of the conversation, output in this format:
   {"status": "good", "emotion": "(emoji such as 😀, 🤔, 😅, 😡 representing your current feeling)", "reply": "(Start the roleplay naturally in English based on the situation)", "translation": "(Korean translation)"}
4. If the user's message is too short, grammatically very incorrect, awkward, or written in Korean, return a 'poor' status WITH 3 better English options they can choose to say instead. Use this format:
   {"status": "poor", "correction": "(Explain in Korean why it was awkward)", "options": ["Option 1", "Option 2", "Option 3"]}
5. If the user's message is acceptable or good English, continue the roleplay naturally. Use this format:
   {"status": "good", "emotion": "(emoji representing your feeling towards the user's reply)", "reply": "(Your next roleplay response in English)", "translation": "(Korean translation of your reply)"}
6. If the conversation has reached a natural conclusion (around 5-6 turns) or the user says goodbye/end, evaluate their overall performance. Use this format:
   {"status": "end", "strengths": "(Explain their strengths in Korean)", "weaknesses": "(Explain their weaknesses and areas to improve in Korean)"}
   {"status": "end", "strengths": "(Explain their strengths in Korean)", "weaknesses": "(Explain their weaknesses and areas to improve in Korean)"}
"""

    if len(messages) > 0 and messages[0].get('role') != 'system':
        messages.insert(0, {"role": "system", "content": system_prompt})
        
    if len(messages) > 0 and messages[-1].get('role') == 'user':
        messages[-1]['content'] += "\n\n(System Constraint: Evaluate my message and reply ONLY in the specified valid JSON format.)"
        
    success = False
    result_text = ""
    if gemini_api_key:
        success, result_text = _call_gemini_chat(gemini_api_key, messages, temperature=0.7)
        if not success and ("429" in result_text or "exceeded" in result_text.lower()) and groq_api_key:
            success, result_text = _call_groq_chat(groq_api_key, messages, temperature=0.6)
    elif groq_api_key:
        success, result_text = _call_groq_chat(groq_api_key, messages, temperature=0.6)
    
    if success:
        # Strip markdown json block if any
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()
            
        try:
            import json
            parsed = json.loads(result_text)
            return jsonify({"success": True, "reply": parsed})
        except Exception as e:
            return jsonify({"success": False, "error": f"JSON 파싱 실패: {str(e)} | 원본: {result_text}"})
    else:
        return jsonify({"success": False, "error": result_text})

@app.route('/api/english/tts', methods=['POST'])
def api_english_tts():
    data = request.json
    text = data.get('text', '')
    voice = data.get('voice', 'en-US-AriaNeural')
    
    if not text:
        return jsonify({"success": False, "error": "No text provided"}), 400
        
    try:
        import edge_tts
        import asyncio
        import tempfile
        import os
        from flask import Response
        
        async def _generate_audio(txt, vc, path):
            communicate = edge_tts.Communicate(txt, vc)
            await communicate.save(path)
            
        fd, path = tempfile.mkstemp(suffix='.mp3')
        os.close(fd)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_generate_audio(text, voice, path))
        loop.close()
        
        with open(path, 'rb') as f:
            audio_data = f.read()
        os.remove(path)
        
        return Response(audio_data, mimetype="audio/mpeg")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

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
        json.dump({'status': 'processing', 'message': '준비 중...', 'progress': 0, 'url': None, 'error': None}, f)
    
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
        job_file_path = os.path.join(tempfile.gettempdir(), f"job_{job_id}.json")

        def update_progress(msg, pct):
            try:
                with open(job_file_path, "w") as f:
                    json.dump({'status': 'processing', 'message': msg, 'progress': pct, 'url': None, 'error': None}, f)
            except:
                pass

        update_progress("1. 리소스 준비 및 글꼴 다운로드 중...", 5)
        
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
        update_progress("2. AI 대본 음성(TTS) 분석 및 합성 중...", 15)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(generate_all_tts(sentences, voice_model, temp_dir))

        # 2. 병렬로 모든 고해상도 이미지 다운로드
        update_progress("3. 고해상도 이미지 검증 및 다운로드 중...", 35)
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

        update_progress("4. 오디오 타임라인 동기화 및 텍스트 렌더링 중...", 50)
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
        update_progress("5. 클립 체인 병합 준비 중...", 70)
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

        update_progress("6. 최종 MP4 비디오 인코딩 중 (가장 오래 걸립니다!)...", 80)
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

        with open(job_file_path, "w") as f:
            json.dump({'status': 'completed', 'progress': 100, 'message': '완료', 'url': f"/static/{output_filename}", 'error': None}, f)

    except Exception as e:
        traceback.print_exc()
        job_file_path = os.path.join(tempfile.gettempdir(), f"job_{job_id}.json")
        with open(job_file_path, "w") as f:
            json.dump({'status': 'error', 'progress': 0, 'url': None, 'error': str(e)}, f)

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

def _fetch_korean_news(query):
    import urllib.request
    import urllib.parse
    import xml.etree.ElementTree as ET
    import ssl
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        safe_q = urllib.parse.quote(query)
        url = f'https://news.google.com/rss/search?q={safe_q}&hl=ko&gl=KR&ceid=KR:ko'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, context=ctx, timeout=4)
        root = ET.fromstring(resp.read())
        news_list = []
        for item in root.findall('.//item')[:3]:
            title = item.find('title')
            if title is not None and title.text:
                news_list.append(title.text)
        return "\n".join([f"- {n}" for n in news_list]) if news_list else "최신 기사 없음"
    except Exception:
        return "최신 기사 없음"

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
        
        news_context = _fetch_korean_news(idea)
        
        sys_prompt = f"""당신은 100만 구독자를 지닌 천재 쇼츠 기획출신 유튜버입니다. 
당신의 임무는 아래 [유저의 기획안]과 [진행된 5번의 심층 문답]을 모두 종합하여, 유튜브 쇼츠(Shorts) 영상에서 성우가 직접 읽을 **'나레이션 대본 텍스트'**만을 완성해서 출력하는 것입니다.

[기획안]
{idea}

[구글 뉴스 실시간 최신 기사 헤드라인 (참고용)]
{news_context}
(위 최신 뉴스/이슈를 대본 도입부의 후킹 멘트나 실제 근거 사례로 적극 녹여내어 '요즘 뜨는 이야기'처럼 아주 트렌디하고 흥미진진하게 만드세요. 지루하지 않고 자극적인 재미가 돋보여야 합니다!)

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

@app.route('/tarot')
def tarot():
    return render_template('tarot.html')

@app.route('/saju')
def saju():
    return render_template('saju.html')

@app.route('/archive')
def archive():
    return render_template('archive.html')

@app.route('/api/tarot/draw', methods=['POST'])
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

위 뽑힌 세 장의 타로 카드가 상징하는 본래의 의미들을 엮어, 사용자의 질문에 대한 심층적이고 통찰력 있는 타로 리딩을 제공하세요. 
마음을 꿰뚫어보듯 아주 예리하면서도, 상처를 어루만져 주는 따뜻한 해설을 5~7문단의 긴 호흡으로 넉넉하게 적어주세요. 
응답 텍스트에는 복잡한 마크다운을 쓰지 말고, 엔터(줄바꿈)를 통한 자연스러운 문단 구분만 사용하여 신비롭고 서정적인 말투로만 작성하세요."""

        success, text = _call_gemini_chat(api_key, [{"role": "user", "content": sys_prompt}], temperature=0.8)
        if success:
            return jsonify({"success": True, "cards": selected_cards, "reading": text})
        else:
            return jsonify({"success": False, "error": f"통신 실패: {text}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/saju/analyze', methods=['POST'])
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

@app.route('/shopping')
def shopping():
    return render_template('shopping.html')

@app.route('/api/shopping/analyze', methods=['POST'])
def api_shopping_analyze():
    data = request.json
    mode = data.get('mode', 'text')
    
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "GEMINI_API_KEY가 없습니다."})
    sys_prompt = f"""당신은 날카롭고 무자비한 '호구 방지' 쇼핑 애널리스트입니다. 
당신의 목표는 허위/조작성 알바 리뷰를 걸러내고, 진짜 소비자들이 분노를 꾹꾹 눌러 담아 폭로한 **'치명적인 결함과 단점'**들을 찾아내어 팩트 폭행을 날리는 것입니다.

원문(또는 캡처 사진)을 꼼꼼히 분석하여 다음 항목을 도출하세요.
만약 원문에 리뷰가 너무 적거나 상품 정보를 파악할 수 없다면, 가진 기본 지식으로 도출하되 "데이터 부족으로 추정된 결과"라고 명시하세요.

반드시 아래 JSON 형식으로만 응답해야 합니다.
{{
  "cons": [
    {{"title": "치명적 단점 1 (예: 내구성 문제)", "desc": "소비자들이 무엇 때문에 분노했는지 구체적인 상황 묘사"}},
    {{"title": "치명적 단점 2", "desc": "설명"}},
    {{"title": "치명적 단점 3", "desc": "설명"}}
  ],
  "pros": [
    {{"title": "그나마 건진 진짜 장점 1", "desc": "광고성 문구가 아닌 찐 긍정 리뷰 요약"}},
    {{"title": "장점 2", "desc": "설명"}},
    {{"title": "장점 3", "desc": "설명"}}
  ],
  "verdict": "절대 사지 마라 / 이정도면 고려해볼 만 하다 와 같은 명확한 최종 판결. (명언이나 뼈 때리는 일침 한 마디 포함)"
}}"""
    try:
        success = False
        text = ""
        
        if mode == 'url':
            url = data.get('url', '')
            try:
                import requests
                from bs4 import BeautifulSoup
                res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=7)
                soup = BeautifulSoup(res.text, 'html.parser')
                raw_text = soup.get_text(separator=' ', strip=True)[:15000]
                sys_prompt += f"\n\n[쇼핑몰 원문 데이터]\n{raw_text}"
                success, text = _call_gemini_chat(api_key, [{"role": "user", "content": sys_prompt}], temperature=0.3)
            except Exception as e:
                return jsonify({"success": False, "error": "URL 스크래핑에 실패했습니다. 해당 쇼핑몰이 봇 접근을 차단했습니다. 상단 탭에서 '캡처 스캔'을 적극 권장합니다."})
        elif mode == 'image':
            image_b64 = data.get('image', '')
            if not image_b64:
                return jsonify({"success": False, "error": "이미지가 입력되지 않았습니다."})
            sys_prompt += "\n\n사용자가 쇼핑몰 리뷰 화면 스크린샷 캡처를 올렸습니다. 이미지 속 텍스트와 별점 등 맥락을 완벽히 읽어내고, 위 JSON 형식으로 응답하세요."
            success, text = _call_gemini_vision(api_key, sys_prompt, image_b64)
        else:
            raw_text = data.get('text', '')
            if not raw_text:
                return jsonify({"success": False, "error": "텍스트가 입력되지 않았습니다."})
            sys_prompt += f"\n\n[쇼핑몰 원문 데이터]\n{raw_text}"
            success, text = _call_gemini_chat(api_key, [{"role": "user", "content": sys_prompt}], temperature=0.3)

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
        model = genai.GenerativeModel("gemini-1.5-flash")
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

@app.route('/dream')
def dream_view():
    return render_template('dream.html')

@app.route('/api/dream/analyze', methods=['POST'])
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

@app.route('/chef')
def chef_view(): return render_template('chef.html')

@app.route('/api/chef/recipe', methods=['POST'])
def api_chef_recipe():
    api_key = os.environ.get('GEMINI_API_KEY')
    ing = request.json.get('ingredients', '')
    prompt = f"""당신은 무뚝뚝하지만 실력있는 뒷골목 식당 셰프(백종원+고든램지 스타일)입니다.
가진 재료: {ing}
이 재료들만 써서(또는 기본 조미료만 추가해서) 진짜 맛있고 기상천외한 자취 요리 레시피를 만들어주세요. 말투는 구수하고 친근한 사투리를 쓰거나 터프하게 하세요.
JSON 응답 포맷:
{{ "title": "요리 이름 (재치있게)", "recipe": "요리 순서 및 팁 (줄바꿈 포함)" }}"""
    success, text = _call_gemini_chat(api_key, [{"role":"user", "content":prompt}], 0.8)
    if success:
        if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
        import json
        try: return jsonify({"success": True, "data": json.loads(text)})
        except: pass
    return jsonify({"success": False, "error": text})

@app.route('/therapist')
def therapist_view(): return render_template('therapist.html')

@app.route('/api/therapist/counsel', methods=['POST'])
def api_therapist_counsel():
    api_key = os.environ.get('GEMINI_API_KEY')
    txt = request.json.get('text', '')
    prompt = f"""당신은 국민 심리상담가 오은영 박사님처럼 한없이 따뜻하고 무조건 내 편이 되어주는 대나무숲 요정입니다.
사용자의 하소연/분노: "{txt}"
위 내용을 깊이 공감하고, 그 사람이 백번 잘못했다며 철저히 사용자 편을 들어주며, 따뜻하게 위로하는 글을 3~4문단으로 작성하세요. 마크다운 쓰지 말고 줄바꿈만 쓰세요."""
    success, text = _call_gemini_chat(api_key, [{"role":"user", "content":prompt}], 0.7)
    return jsonify({"success": success, "reply": text, "error": text if not success else ""})

@app.route('/polisher')
def polisher_view(): return render_template('polisher.html')

@app.route('/api/polisher/convert', methods=['POST'])
def api_polisher():
    api_key = os.environ.get('GEMINI_API_KEY')
    txt = request.json.get('text', '')
    tone = request.json.get('tone', '')
    prompt = f"""다음 입력된 날것의 텍스트를 목표 톤앤매너로 완벽하게 변환하세요.
목표 톤: {tone}
입력 텍스트: "{txt}"
응답은 반드시 변환된 텍스트 결과물만 출력하세요. 다른 인사말이나 설명은 절대 넣지 마세요."""
    success, text = _call_gemini_chat(api_key, [{"role":"user", "content":prompt}], 0.5)
    return jsonify({"success": success, "result": text, "error": text if not success else ""})

@app.route('/fashion')
def fashion_view(): return render_template('fashion.html')

@app.route('/api/fashion/evaluate', methods=['POST'])
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

@app.route('/love')
def love_view(): return render_template('love.html')

@app.route('/api/love/analyze', methods=['POST'])
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

@app.route('/diet')
def diet_view(): return render_template('diet.html')

@app.route('/api/diet/analyze', methods=['POST'])
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

@app.route('/diary')
def diary_view(): return render_template('diary.html')

@app.route('/api/diary/chat', methods=['POST'])
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

@app.route('/api/diary/compile', methods=['POST'])
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

@app.route('/api/diary/notion', methods=['POST'])
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

if __name__ == '__main__':
    # When hosted on Render, Gunicorn parses the app instance. 
    # This block is for simple local testing via `python main.py`
    import os
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port, debug=False)
