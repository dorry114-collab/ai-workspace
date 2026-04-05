from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd
import numpy as np
import datetime
from sklearn.linear_model import LinearRegression
import urllib.request
import ssl
import requests
import FinanceDataReader as fdr
import yt_dlp
import threading
import webbrowser
import os

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
        hist['SMA_50'] = hist['Close'].rolling(window=50).mean()
        
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
        if len(recent_data) > 30 and os.environ.get('GROQ_API_KEY'):
            api_key = os.environ.get('GROQ_API_KEY')
            current_p = recent_data['Close'].iloc[-1]
            high_1m = recent_data['High'].tail(21).max() if 'High' in recent_data else current_p
            low_1m = recent_data['Low'].tail(21).min() if 'Low' in recent_data else current_p
            sma50 = hist['SMA_50'].iloc[-1]
            rsi = hist['RSI'].iloc[-1]
            
            sma50_str = f"{sma50:.2f}" if pd.notnull(sma50) else "N/A"
            rsi_str = f"{rsi:.2f}" if pd.notnull(rsi) else "N/A"
            
            p_prompt = f"""당신은 세계 최고의 월스트리트 기술적 차트 분석가입니다.
종목: {ticker} ({raw_ticker})
현재가: {current_p:.2f}
최근 1개월 최고가: {high_1m:.2f} / 최저가: {low_1m:.2f}
50일 이동평균선: {sma50_str}
현재 RSI (14일): {rsi_str}

위 기술적 지표들을 종합하여 향후 차트 전개 방향을 예측하세요. 
반드시 아래 JSON 형식으로만 응답해야 합니다.
{{
  "analysis": "초보자도 이해할 수 있는 친절한 차트 분석 (4~5문장). 한자(Hanja)는 단 한 글자도 쓰지 말고 100% 자연스러운 한국어(한글)로만 작성하세요. RSI, 이동평균선, 지지선/저항선 등의 전문 용어를 언급할 때, 그게 무슨 뜻인지(예: 'RSI는 단기 과열을 보여주는데 현재 30이라 너무 많이 떨어져서 반등이 기대됩니다' 등)를 반드시 풀어서 친절하게 설명하며 분석결과를 알려주세요. 마치 1타 강사가 초보자에게 차트 공부를 시켜주듯 다정하게 작성해야 합니다.",
  "target_price": 1개월 뒤 현실적인 목표가(숫자만),
  "stop_loss": 현재 지지라인 기반의 명확한 손절가(숫자만)
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
            'ai_analysis': ai_data
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
        if not handle.startswith('@') and 'youtube.com/' not in handle:
            handle = '@' + handle
            
        channels_url = f"https://youtube.googleapis.com/youtube/v3/channels?part=id&forHandle={handle}&key={api_key}"
        try:
            resp = requests.get(channels_url)
            data = resp.json()
            if 'items' in data and len(data['items']) > 0:
                channel_id = data['items'][0]['id']
        except Exception as e:
            pass
            
    if not channel_id:
        return {"success": False, "error": f"채널({channel_input})을 찾을 수 없습니다. 정확한 @핸들 형식이나 채널 프로필 URL을 기입해주세요."}
        
    # 2. Fetch Top X by exact viewCount via Pagination
    import html
    video_ids = []
    video_titles = {}
    
    next_page_token = ""
    try:
        while len(video_ids) < limit:
            q_limit = min(50, limit - len(video_ids))
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
            
        return {"success": True, "data": results[:limit], "channel": channel_input}
        
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

def _call_groq(api_key, sys_prompt):
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
            {"role": "system", "content": "당신은 세계 최고의 프롬프트 엔지니어입니다."},
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

# --- ROUTES ---
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/youtube')
def youtube():
    return render_template('youtube.html')

@app.route('/stock')
def stock():
    return render_template('stock.html')

@app.route('/prompt')
def prompt():
    return render_template('prompt.html')


if __name__ == '__main__':
    # When hosted on Render, Gunicorn parses the app instance. 
    # This block is for simple local testing via `python main.py`
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port, debug=False)
