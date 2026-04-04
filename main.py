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
            
        return jsonify({
            'success': True,
            'ticker': ticker,
            'original_ticker': raw_ticker,
            'historical': historical_data,
            'predictions': predictions,
            'past_predictions': past_predictions,
            'pred_days': prediction_days
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
def _call_groq(api_key, sys_prompt):
    import requests
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": "llama3-70b-8192",
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
    if not idea:
        return jsonify({"success": False, "error": "아이디어를 입력해주세요."})
        
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        return jsonify({"success": False, "error": "[필수] Groq API 키가 없습니다. Render Environment에 GROQ_API_KEY를 등록해주세요."})
        
    try:
        sys_prompt = f"""당신은 세계 최고의 프롬프트 엔지니어입니다.
사용자가 다음의 작업을 수행하는 AI 프롬프트를 만들고 싶어합니다:
"{idea}"

이 프롬프트를 완벽하고 구체적인 지시문을 갖춘 템플릿으로 완성하기 위해, 사용자에게 의도를 묻는 핵심 역질문 5가지를 생성하세요. (타겟, 분량, 어조, 필수 포함사항 등)
반드시 아래의 JSON 배열 형식으로만 응답해야 합니다. 다른 말은 절대 하지 마세요.
[
  {{"id": 1, "question": "질문 내용...", "example": "예: ... 와 같이 적어주세요."}},
  {{"id": 2, "question": "...", "example": "..."}}
]"""
        success, text = _call_groq(api_key, sys_prompt)
        
        if not success:
            return jsonify({"success": False, "error": f"모든 AI 모델 통신 실패 (최종 오류): {text}"})
            
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        import json
        questions = json.loads(text)
        return jsonify({"success": True, "questions": questions[:5]})
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
