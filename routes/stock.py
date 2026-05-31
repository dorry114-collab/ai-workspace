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

stock_bp = Blueprint('stock', __name__)

ssl._create_default_https_context = ssl._create_unverified_context

import requests
_orig_request = requests.api.request
def _patched_request(method, url, **kwargs):
    if 'timeout' not in kwargs:
        if 'googleapis' in str(url) or 'groq' in str(url):
            kwargs['timeout'] = 25.0
        else:
            kwargs['timeout'] = 5.0
    return _orig_request(method, url, **kwargs)
requests.api.request = _patched_request
requests.request = _patched_request

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


# --- PROMPT OPTIMIZER LOGIC ---
GROQ_MODEL_CACHE = None

def get_best_groq_model(api_key):
    
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


@stock_bp.route('/api/stock')
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
            
            p_prompt = f"""당신은 월스트리트의 전설적인 투자 기관 출신의 차트 분석 최고 전문가입니다. 제공된 차트 지표들을 엄격하고 논리적인 기술적 분석(Technical Analysis) 기법으로 진단해 주세요.
오직 100% 자연스러운 한국어(Korean)로만 대답해야 합니다.

종목: {ticker} ({raw_ticker})
현재가: {current_p:.2f}
최근 1개월 최고가: {high_1m:.2f} / 최저가: {low_1m:.2f}
장기 평균 가격선(SMA 50): {sma50_str}
시장 과열점수(RSI): {rsi_str} (70 이상은 위험, 30 이하는 안전)
볼린저 밴드 상단: {bb_upper_str} / 하단: {bb_lower_str}
MACD: {macd_str} (시그널 {macd_sig_str})
최근 거래량: {vol_trend_str} (평소 대비 {vol_ratio:.1f}%)

위 기술적 지표들을 종합하여, 현재 주가 흐름에 대한 날카롭고 전문적인 차트 분석을 제공해 주세요. 

🔥 **[전문가 차트 검토 지침]**:
1. **유기적 지표 분석**: 단일 지표만 보지 말고, 가격이 볼린저 밴드 상/하단선에 위치한 상태에서 RSI 과열 여부, MACD 크로스오버 방향, 거래량 변화 추이를 결합하여 추세의 강도와 신뢰성을 논리적으로 판정하십시오. (예: "주가는 볼린저 밴드 상단을 돌파했으나 RSI가 80을 상회하고 거래량이 감소하여 단기 다이버전스(Divergence)에 의한 저항 우려가...")
2. **이동평균선 및 지지/저항 구조 분석**: 현재 주가와 단/장기 이평선(SMA50)의 이격도, 최근 1개월 최고가/최저가로 형성된 강력한 박스권 상단 저항선 및 하단 지지선을 정확히 연계하여 분석하십시오.
3. **정확한 수치 및 용어 인용**: 분석글을 작성할 때 반드시 제공된 **'정확한 수치'**와 **'전문 명칭(SMA, RSI, MACD, 볼린저 밴드 등)'**을 문장 안에 명확하게 인용하여 작성하세요. 초보자도 쉽게 이해할 수 있도록 분석글 하단에는 '용어 해설표'를 반드시 별도로 마련하여 짧고 명확하게 뜻을 풀이해 주세요.

**[목표가 및 손절가 설정 규칙]**:
이 서비스는 개인 투자자를 위한 '현물 매수(Long Only)' 중심 서비스입니다. 따라서 **매매 의견(추천)에 상관없이 반드시 목표가는 현재가보다 높아야 하고(목표가 > 현재가), 손절가는 현재가보다 낮아야 합니다(손절가 < 현재가).**
공매도(Short) 기준의 거꾸로 된 가격 설정(목표가가 현재가보다 낮고 손절가가 현재가보다 높은 설정)은 절대로 허용되지 않습니다.
현재가가 {current_p:.0f}원이므로, 목표가는 반드시 {current_p:.0f}원보다 큰 정수값으로, 손절가는 반드시 {current_p:.0f}원보다 작은 정수값으로 설정해 주세요.

**[차트 지표 기반의 정밀 산출 규칙]**:
- 목표가와 손절가는 단순한 임의의 숫자가 아닙니다. 반드시 제공된 기술적 지표(1개월 최고/최저가, 볼린저 밴드 상/하단선, 장기 평균 가격선 SMA50 등)를 저항선과 지지선으로 삼아 논리적으로 산출해 주세요.
- **목표가(target_price)**는 현재가보다 높은 실질적 저항선(예: 1개월 최고가, 볼린저 밴드 상단선 등)을 기준으로 산정합니다.
- **손절가(stop_loss)**는 현재가보다 낮은 실질적 지지선(예: SMA50 평균 가격선, 1개월 최저가, 볼린저 밴드 하단선 등)을 기준으로 산정합니다.
- 분석글 본문("analysis" 필드) 내에 어떤 차트 지표(예: "1개월 최저가인 XXX원 부근의 강력한 지지선을 손절 기준으로 삼고, 볼린저 밴드 상단선인 XXX원을 목표가로...")를 지지와 저항으로 삼아 목표가와 손절가를 도출했는지 구체적인 기술적 분석 근거를 반드시 포함하십시오.

반드시 아래 JSON 형식으로만 응답해야 합니다.
{{
  "analysis": "제공된 가격 수치와 지표 명칭(RSI, MACD 등) 및 목표가/손절가의 차트 지표 기반 산출 근거를 적극적으로 본문에 인용하여 작성한 5~7문장 분량의 전문가적 차트 분석. (단, 문단이 구분되도록 확실하게 줄바꿈 문자를 넣고, 본문 끝에는 빈 줄을 넣은 뒤 '\\n\\n---\\n[용어 해설]\\n- MACD: ...\\n- RSI: ...' 형태로 가독성을 극대화하여 덧붙일 것)",
  "target_price": 1개월 뒤 합리적인 목표가격(반드시 현재가보다 큰 숫자만 입력),
  "stop_loss": 손절매(위험관리) 목표 가격(반드시 현재가보다 작은 숫자만 입력)
}}"""

            try:
                sys_role = "당신은 월스트리트 출신의 수석 주식 퀀트이자 차트 분석 전문가입니다. 제공된 모든 기술적 데이터(RSI, MACD, 볼린저 밴드, SMA 가격선, 거래량 추세 등)를 유기적으로 연결하여, 단순 요약이 아닌 실제 전문 기관 리포트 수준의 명확하고 깊이 있는 차트 분석을 제공합니다."

                messages = [
                    {"role": "system", "content": sys_role},
                    {"role": "user", "content": p_prompt}
                ]
                success, text = _call_gemini_chat(api_key, messages, temperature=0.5)
                if success:
                    if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
                    elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
                    import json
                    try:
                        ai_data = json.loads(text)
                        if ai_data and isinstance(ai_data, dict):
                            if 'target_price' in ai_data and 'stop_loss' in ai_data:
                                try:
                                    target = float(ai_data['target_price'])
                                    stop = float(ai_data['stop_loss'])
                                    
                                    # Swap target & stop if they are inverted
                                    if target < stop:
                                        ai_data['target_price'] = int(stop)
                                        ai_data['stop_loss'] = int(target)
                                        target, stop = stop, target
                                    
                                    # Ensure target > current_p and stop < current_p
                                    if target <= current_p:
                                        ai_data['target_price'] = int(current_p * 1.10)
                                    if stop >= current_p:
                                        ai_data['stop_loss'] = int(current_p * 0.90)
                                except Exception as inner_err:
                                    print(f"Error correcting single stock target/stop price: {inner_err}")
                    except Exception as e:
                        print(f"Error decoding single stock JSON: {e}")
                        ai_data = None
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


@stock_bp.route('/stock')
def stock():
    return render_template('stock.html')


@stock_bp.route('/market')
def market():
    return render_template('market.html')


@stock_bp.route('/api/stock/market_trend')
def get_market_trend():
    try:
        import FinanceDataReader as fdr
        import concurrent.futures
        import datetime
        import numpy as np
        import pandas as pd
        import json

        # 날짜 파라미터 처리 (YYYY-MM-DD 형식, 없으면 오늘)
        date_str = request.args.get('date', '')
        if date_str:
            try:
                target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                return jsonify({'success': False, 'error': '날짜 형식이 잘못되었습니다. YYYY-MM-DD 형식으로 입력해주세요.'})
        else:
            target_date = datetime.datetime.now()

        data_date = target_date.strftime('%Y-%m-%d')

        top_stocks = []
        
        # 날짜가 오늘인지 확인 (오늘이면 실시간 네이버 크롤러 우선 사용)
        is_today = target_date.date() == datetime.date.today() or not date_str
        
        if is_today:
            try:
                # 네이버 금융 크롤러 (KOSPI/KOSDAQ 시가총액 상위 + 거래량 상위 결합)
                # Render 서버의 해외 IP 차단(KRX 공식 사이트 차단)을 우회하고 실제 거래대금 탑 10 추출
                def get_market_cap_stocks(sosok, page):
                    url = f'https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}'
                    headers = {'User-Agent': 'Mozilla/5.0'}
                    res = requests.get(url, headers=headers, timeout=5.0)
                    res.encoding = 'euc-kr'
                    soup = BeautifulSoup(res.text, 'html.parser')
                    table = soup.select_one('table.type_2')
                    if not table: return []
                    
                    stocks = []
                    rows = table.select('tr')
                    for row in rows[1:]:
                        tds = [td.text.strip() for td in row.find_all('td')]
                        if len(tds) < 12 or not tds[1]: continue
                        name = tds[1]
                        
                        skip_keywords = ['KODEX', 'TIGER', 'KBSTAR', 'ARIRANG', 'SOL', 'ACE', 'HANARO', 'KOSEF', 'ETN', '인버스', '레버리지', '선물', '국채']
                        if any(kw in name for kw in skip_keywords): continue
                            
                        code = ''
                        a_tag = row.find('a', class_='tltle')
                        if a_tag and 'code=' in a_tag['href']:
                            code = a_tag['href'].split('code=')[1].split('&')[0]
                            
                        try:
                            close = float(tds[2].replace(',', ''))
                        except:
                            close = 0.0
                            
                        raw_ratio = tds[4].replace('%', '').strip()
                        try:
                            changes_ratio = float(raw_ratio)
                        except:
                            changes_ratio = 0.0
                            
                        try:
                            all_tds = row.find_all('td')
                            vol_str = all_tds[9].text.strip().replace(',', '')
                            volume = int(vol_str)
                        except:
                            volume = 0
                            
                        amount = close * volume
                        stocks.append({
                            'code': code,
                            'name': name,
                            'close': close,
                            'changes_ratio': changes_ratio,
                            'volume': volume,
                            'amount': amount,
                            'market': 'KOSPI' if sosok == 0 else 'KOSDAQ'
                        })
                    return stocks

                def get_volume_stocks(sosok):
                    url = f'https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}'
                    headers = {'User-Agent': 'Mozilla/5.0'}
                    res = requests.get(url, headers=headers, timeout=5.0)
                    res.encoding = 'euc-kr'
                    soup = BeautifulSoup(res.text, 'html.parser')
                    table = soup.select_one('table.type_2')
                    if not table: return []
                    
                    stocks = []
                    rows = table.select('tr')
                    for row in rows[1:]:
                        tds = [td.text.strip() for td in row.find_all('td')]
                        if len(tds) < 10 or not tds[1]: continue
                        name = tds[1]
                        
                        skip_keywords = ['KODEX', 'TIGER', 'KBSTAR', 'ARIRANG', 'SOL', 'ACE', 'HANARO', 'KOSEF', 'ETN', '인버스', '레버리지', '선물', '국채']
                        if any(kw in name for kw in skip_keywords): continue
                            
                        code = ''
                        a_tag = row.find('a', class_='tltle')
                        if a_tag and 'code=' in a_tag['href']:
                            code = a_tag['href'].split('code=')[1].split('&')[0]
                            
                        try:
                            close = float(tds[2].replace(',', ''))
                        except:
                            close = 0.0
                            
                        raw_ratio = tds[4].replace('%', '').strip()
                        try:
                            changes_ratio = float(raw_ratio)
                        except:
                            changes_ratio = 0.0
                            
                        try:
                            volume = int(tds[5].replace(',', ''))
                        except:
                            volume = 0
                            
                        try:
                            amount = int(tds[6].replace(',', '')) * 1000000
                        except:
                            amount = 0
                            
                        stocks.append({
                            'code': code,
                            'name': name,
                            'close': close,
                            'changes_ratio': changes_ratio,
                            'volume': volume,
                            'amount': amount,
                            'market': 'KOSPI' if sosok == 0 else 'KOSDAQ'
                        })
                    return stocks

                from bs4 import BeautifulSoup
                stocks_map = {}
                # KOSPI 시총 상위 1~100위, KOSDAQ 시총 상위 1~100위, 그리고 당일 KOSPI/KOSDAQ 거래량 상위 1~100위 수집 후 결합
                # 네트워크 성능 향상을 위해 멀티스레딩 병렬 수집
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                    futures = [
                        executor.submit(get_market_cap_stocks, 0, 1),
                        executor.submit(get_market_cap_stocks, 0, 2),
                        executor.submit(get_market_cap_stocks, 1, 1),
                        executor.submit(get_market_cap_stocks, 1, 2),
                        executor.submit(get_volume_stocks, 0),
                        executor.submit(get_volume_stocks, 1)
                    ]
                    results = [f.result() for f in concurrent.futures.as_completed(futures)]
                
                for r in results:
                    for s in r:
                        stocks_map[s['code']] = s

                all_stocks = list(stocks_map.values())
                all_stocks.sort(key=lambda x: x['amount'], reverse=True)
                top_stocks = all_stocks[:10]
            except Exception as crawler_err:
                print(f"Naver crawler failed: {crawler_err}")
                top_stocks = []

        # 크롤러가 실패했거나 오늘 날짜가 아니면 기존 KRX -> Fallback 로직 작동
        if not top_stocks:
            try:
                df = fdr.StockListing('KRX', date=data_date)
                df = df[df['Amount'].notna()]
                df_sorted = df.sort_values(by='Amount', ascending=False).head(10)

                for idx, row in df_sorted.iterrows():
                    raw_ratio = row.get('ChagesRatio', row.get('ChangeRatio', row.get('Changes', None)))
                    try:
                        changes_ratio = float(raw_ratio) if raw_ratio is not None else 0.0
                    except:
                        changes_ratio = 0.0

                    top_stocks.append({
                        'code': str(row['Code']).zfill(6),
                        'name': str(row['Name']),
                        'market': str(row.get('Market', 'KRX')),
                        'close': float(row['Close']),
                        'changes_ratio': changes_ratio,
                        'volume': int(row['Volume']) if row.get('Volume') else 0,
                        'amount': int(row['Amount'])
                    })
            except Exception as e:
                print(f"KRX Fetch Failed, using fallback: {e}")
                fallback_codes = [
                    ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("042700", "한미반도체"), 
                    ("068270", "셀트리온"), ("005380", "현대차"), ("000270", "기아"), 
                    ("035420", "NAVER"), ("035720", "카카오"), ("373220", "LG에너지솔루션"), 
                    ("207940", "삼성바이오로직스"), ("104480", "티케케미칼"), ("012450", "한화에어로스페이스"),
                    ("028300", "HLB"), ("247540", "에코프로비엠"), ("086520", "에코프로")
                ]
                fetch_start = (target_date - datetime.timedelta(days=10)).strftime('%Y-%m-%d')
                fetch_end = (target_date + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
                
                # Fallback 종목의 데이터를 병렬 수집
                def get_fallback_stock(code_name):
                    code, name = code_name
                    try:
                        hist = fdr.DataReader(code, fetch_start, fetch_end)
                        if not hist.empty:
                            hist.index = pd.to_datetime(hist.index)
                            valid_rows = hist[hist.index <= pd.Timestamp(target_date)]
                            if not valid_rows.empty:
                                last_row = valid_rows.iloc[-1]
                                prev_row = valid_rows.iloc[-2] if len(valid_rows) > 1 else last_row
                                close = float(last_row['Close'])
                                prev_close = float(prev_row['Close'])
                                changes_ratio = ((close - prev_close) / prev_close) * 100 if prev_close > 0 else 0
                                vol = int(last_row['Volume'])
                                amt = close * vol
                                return {
                                    'code': code,
                                    'name': name,
                                    'market': 'KRX',
                                    'close': close,
                                    'changes_ratio': changes_ratio,
                                    'volume': vol,
                                    'amount': amt
                                }
                    except:
                        pass
                    return None

                with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                    fallback_results = list(executor.map(get_fallback_stock, fallback_codes))
                
                top_stocks = [r for r in fallback_results if r is not None]
                top_stocks = sorted(top_stocks, key=lambda x: x['amount'], reverse=True)[:10]

        if not top_stocks:
            return jsonify({'success': False, 'error': 'KRX 서버가 응답하지 않거나 접근이 차단되었습니다 (해외 IP 차단 가능성).'})

        # 등락률 및 지표 통합 수집 (네트워크 1회만 호출하여 시간 50% 단축)
        def fetch_stats_and_verify(item):
            try:
                start_date = (target_date - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
                end_date = target_date.strftime('%Y-%m-%d')
                hist = fdr.DataReader(item['code'], start_date, end_date)
                if not hist.empty:
                    # 해당 날짜의 실제 종가로 보정 및 등락률 재검증
                    hist.index = pd.to_datetime(hist.index)
                    valid_rows = hist[hist.index <= pd.Timestamp(target_date)]
                    if len(valid_rows) >= 2:
                        close = float(valid_rows.iloc[-1]['Close'])
                        prev_close = float(valid_rows.iloc[-2]['Close'])
                        if prev_close > 0:
                            item['changes_ratio'] = ((close - prev_close) / prev_close) * 100
                            item['close'] = close

                    valid_rows = valid_rows.copy()
                    valid_rows['SMA_20'] = valid_rows['Close'].rolling(window=20).mean()
                    delta = valid_rows['Close'].diff()
                    gain = delta.where(delta > 0, 0)
                    loss = -delta.where(delta < 0, 0)
                    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
                    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
                    rs = avg_gain / avg_loss
                    valid_rows['RSI'] = 100 - (100 / (1 + rs))
                    
                    # Bollinger Bands
                    valid_rows['STD_20'] = valid_rows['Close'].rolling(window=20).std()
                    valid_rows['BB_Upper'] = valid_rows['SMA_20'] + (valid_rows['STD_20'] * 2)
                    valid_rows['BB_Lower'] = valid_rows['SMA_20'] - (valid_rows['STD_20'] * 2)
                    
                    last_row = valid_rows.iloc[-1]
                    item['sma_20'] = float(last_row['SMA_20']) if not pd.isna(last_row['SMA_20']) else None
                    item['rsi'] = float(last_row['RSI']) if not pd.isna(last_row['RSI']) else None
                    item['high_1m'] = float(valid_rows['High'].tail(21).max())
                    item['low_1m'] = float(valid_rows['Low'].tail(21).min())
                    item['bb_upper'] = float(last_row['BB_Upper']) if not pd.isna(last_row['BB_Upper']) else None
                    item['bb_lower'] = float(last_row['BB_Lower']) if not pd.isna(last_row['BB_Lower']) else None
            except Exception as e:
                print(f"Error fetching stats for {item['code']}: {e}")
            return item

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            top_stocks = list(executor.map(fetch_stats_and_verify, top_stocks))

        ai_data = None
        if os.environ.get('GEMINI_API_KEY'):
            api_key = os.environ.get('GEMINI_API_KEY')
            
            context_lines = []
            for i, s in enumerate(top_stocks):
                v_sma = s.get('sma_20')
                sma_str = f"{v_sma:.0f}" if v_sma is not None else "N/A"
                v_rsi = s.get('rsi')
                rsi_str = f"{v_rsi:.1f}" if v_rsi is not None else "N/A"
                v_high = s.get('high_1m')
                high_str = f"{v_high:.0f}" if v_high is not None else "N/A"
                v_low = s.get('low_1m')
                low_str = f"{v_low:.0f}" if v_low is not None else "N/A"
                v_bb_upper = s.get('bb_upper')
                bb_upper_str = f"{v_bb_upper:.0f}" if v_bb_upper is not None else "N/A"
                v_bb_lower = s.get('bb_lower')
                bb_lower_str = f"{v_bb_lower:.0f}" if v_bb_lower is not None else "N/A"
                
                context_lines.append(
                    f"{i+1}위: {s['name']} (종목코드:{s['code']}, 현재가: {s['close']:.0f}원, 등락률: {s['changes_ratio']:.2f}%, 거래대금: {s['amount']:,}원) "
                    f"[지표: SMA20={sma_str}, RSI={rsi_str}, 1달최고={high_str}, 1달최저={low_str}, 볼린저밴드_하단={bb_lower_str}, 볼린저밴드_상단={bb_upper_str}]"
                )
            context_str = "\n".join(context_lines)
            
            sys_role = "당신은 월스트리트의 일류 펀드매니저이자 계량적 차트분석 수석 애널리스트입니다. 응답은 반드시 JSON 형식으로만 작성하세요."
            p_prompt = f"""오늘 한국 주식시장 거래대금 상위 10종목과 그 기술적 지표(최근 1개월 기준)는 다음과 같습니다:

{context_str}

이 데이터를 바탕으로 다음 2가지를 분석해 주세요:
1. 시장 전체의 흐름과 주도 테마에 대한 전반적인 시황 분석 (마크다운 형식, 3~4문단)
2. 10개 종목 각각에 대한 냉철한 매매 의견(적극 매수, 매수, 관망, 매도 중 택 1), 합리적인 1개월 목표가(숫자), 손절가(숫자), 그리고 한 줄 핵심 근거(1~2문장).

**[전문가 차트 검토 지침]**:
1. **유기적 지표 분석**: 단일 지표만 보지 말고, 가격이 볼린저 밴드 상/하단선에 위치한 상태에서 RSI 과열 여부, SMA20 돌파 강도 등을 결합하여 주세의 강도와 신뢰성을 논리적으로 판정하십시오.
2. **목표가와 손절가 설정의 필연성**: 분석 글에서 언급한 기술적 지지선(예: SMA20 선 혹은 1달최저 등)을 바탕으로 손절가를 설정하고, 저항선(예: 볼린저 밴드 상단 혹은 1달최고)을 바탕으로 목표가를 산출한 논리적 근거가 매 종목의 핵심 근거("reason")에 명확히 명시되도록 하십시오.

**[목표가 및 손절가 설정 규칙]**:
이사비스는 개인 투자자를 위한 '현물 매수(Long Only)' 중심 서비스입니다. 따라서 **매매 의견(추천)에 상관없이(매도, 관망 의견이더라도) 반드시 목표가는 각 종목의 현재가보다 높아야 하고(목표가 > 현재가), 손절가는 각 종목의 현재가보다 낮아야 합니다(손절가 < 현재가).**
공매도(Short) 기준의 거꾸로 된 가격 설정(목표가가 현재가보다 낮고 손절가가 현재가보다 높은 설정)은 절대로 허용되지 않습니다. 매도(Sell)나 관망(Hold) 의견이더라도 향후 반등 시 목표할 수 있는 상방 저항선을 목표가로, 하방 지지선을 손절가로 설정하세요.

**[차트 지표 기반의 정밀 산출 규칙]**:
- 목표가와 손절가는 단순한 임의의 추정치가 아닙니다. 반드시 제공된 각 종목의 구체적인 차트 지표(최근 1개월 최고가/최저가, SMA20 가격선, 볼린저 밴드 가격 등)를 저항선과 지지선으로 삼아 논리적으로 산출해 주세요.
- **목표가(target_price)**는 현재가보다 높은 실질적 저항선(예: 1개월 최고가 부근, 볼린저 밴드 상단선 등)을 기준으로 산정합니다.
- **손절가(stop_loss)**는 현재가보다 낮은 실질적 지지선(예: SMA20 가격선, 1개월 최저가 등)을 기준으로 산정합니다.
- 매 종목의 핵심 근거("reason" 필드)에 목표가와 손절가를 설정할 때 어떤 구체적인 차트 지표(예: "최근 1개월 최저가인 XXX원 지지를 전제로 손절가를 설정하고, 볼린저 밴드 상단선 돌파 가능성을 감안하여 목표가 XXX원을 산정함")를 지지와 저항으로 참고했는지 명확하게 포함시키십시오.

반드시 아래 JSON 형식으로 응답하세요:
{{
  "overall_summary": "마크다운 형식의 시황 요약글...",
  "stock_analysis": [
    {{
      "code": "종목코드",
      "recommendation": "적극 매수, 매수, 관망, 매도 중 택 1",
      "target_price": 85000,
      "stop_loss": 75000,
      "reason": "최근 1개월 최저가인 72000원 지지 확인으로 손절가를 설정하고, 전고점 저항선인 85000원을 돌파 목표가로 설정하여 매수를 추천함"
    }}
  ]
}}"""
            messages = [
                {"role": "system", "content": sys_role},
                {"role": "user", "content": p_prompt}
            ]
            
            success, text = _call_gemini_chat(api_key, messages, temperature=0.5)
            if success:
                try:
                    if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
                    elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
                    ai_data = json.loads(text)
                    if ai_data and 'stock_analysis' in ai_data and isinstance(ai_data['stock_analysis'], list):
                        # Create mapping of clean stock code -> close price
                        price_map = {}
                        for s in top_stocks:
                            clean_code = str(s['code']).split('.')[0].zfill(6)
                            price_map[clean_code] = float(s['close'])
                        
                        for item in ai_data['stock_analysis']:
                            item_code = str(item.get('code', '')).split('.')[0].zfill(6)
                            current_p = price_map.get(item_code)
                            if current_p:
                                try:
                                    target = float(item.get('target_price', 0))
                                    stop = float(item.get('stop_loss', 0))
                                    
                                    # Swap target & stop if they are inverted
                                    if target < stop:
                                        item['target_price'] = int(stop)
                                        item['stop_loss'] = int(target)
                                        target, stop = stop, target
                                    
                                    # Ensure target > current_p and stop < current_p
                                    if target <= current_p:
                                        item['target_price'] = int(current_p * 1.10)
                                    if stop >= current_p:
                                        item['stop_loss'] = int(current_p * 0.90)
                                except Exception as item_err:
                                    print(f"Error correcting market trend stock {item_code}: {item_err}")
                except Exception as e:
                    print(f"JSON Parse Error: {e}\n{text}")
                    ai_data = None
                
        return jsonify({
            'success': True,
            'top_stocks': top_stocks,
            'ai_report': ai_data,
            'data_date': data_date
        })
    except Exception as e:
        print(f"Market Trend Error: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)})
