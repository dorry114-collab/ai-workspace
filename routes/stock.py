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
        
        top_stocks = []
        try:
            df = fdr.StockListing('KRX')
            df = df[df['Amount'].notna()]
            df_sorted = df.sort_values(by='Amount', ascending=False).head(10)
            
            for idx, row in df_sorted.iterrows():
                top_stocks.append({
                    'code': str(row['Code']).zfill(6),
                    'name': str(row['Name']),
                    'market': str(row.get('Market', 'KRX')),
                    'close': float(row['Close']),
                    'changes_ratio': float(row['ChagesRatio']),
                    'volume': int(row['Volume']),
                    'amount': int(row['Amount'])
                })
        except Exception as e:
            # Fallback for Render deployment (KRX blocks foreign IPs)
            print(f"KRX Fetch Failed, using fallback: {e}")
            fallback_codes = [
                ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("042700", "한미반도체"), 
                ("068270", "셀트리온"), ("005380", "현대차"), ("000270", "기아"), 
                ("035420", "NAVER"), ("035720", "카카오"), ("373220", "LG에너지솔루션"), 
                ("207940", "삼성바이오로직스"), ("104480", "티케이케미칼"), ("012450", "한화에어로스페이스"),
                ("028300", "HLB"), ("247540", "에코프로비엠"), ("086520", "에코프로")
            ]
            today_str = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d')
            for code, name in fallback_codes:
                try:
                    hist = fdr.DataReader(code, today_str)
                    if not hist.empty:
                        last_row = hist.iloc[-1]
                        prev_row = hist.iloc[-2] if len(hist) > 1 else last_row
                        close = float(last_row['Close'])
                        prev_close = float(prev_row['Close'])
                        changes_ratio = ((close - prev_close) / prev_close) * 100 if prev_close > 0 else 0
                        vol = int(last_row['Volume'])
                        amt = close * vol
                        top_stocks.append({
                            'code': code,
                            'name': name,
                            'market': 'KRX',
                            'close': close,
                            'changes_ratio': changes_ratio,
                            'volume': vol,
                            'amount': amt
                        })
                except: pass
            top_stocks = sorted(top_stocks, key=lambda x: x['amount'], reverse=True)[:10]

        if not top_stocks:
            return jsonify({'success': False, 'error': 'KRX 서버가 응답하지 않거나 접근이 차단되었습니다 (해외 IP 차단 가능성).'})

            
        def fetch_stats(item):
            try:
                start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
                hist = fdr.DataReader(item['code'], start_date)
                if not hist.empty:
                    hist['SMA_20'] = hist['Close'].rolling(window=20).mean()
                    delta = hist['Close'].diff()
                    gain = delta.where(delta > 0, 0)
                    loss = -delta.where(delta < 0, 0)
                    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
                    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
                    rs = avg_gain / avg_loss
                    hist['RSI'] = 100 - (100 / (1 + rs))
                    
                    last_row = hist.iloc[-1]
                    item['sma_20'] = float(last_row['SMA_20']) if not pd.isna(last_row['SMA_20']) else None
                    item['rsi'] = float(last_row['RSI']) if not pd.isna(last_row['RSI']) else None
                    item['high_1m'] = float(hist['High'].tail(21).max())
                    item['low_1m'] = float(hist['Low'].tail(21).min())
            except Exception as e:
                pass
            return item

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            top_stocks = list(executor.map(fetch_stats, top_stocks))

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
                
                context_lines.append(
                    f"{i+1}위: {s['name']} (종목코드:{s['code']}, 현재가: {s['close']:.0f}원, 등락률: {s['changes_ratio']:.2f}%, 거래대금: {s['amount']:,}원) "
                    f"[지표: SMA20={sma_str}, RSI={rsi_str}, 1달최고={high_str}, 1달최저={low_str}]"
                )
            context_str = "\n".join(context_lines)
            
            sys_role = "당신은 월스트리트의 전설적인 트레이더이자 냉철한 주식 애널리스트입니다. 응답은 반드시 JSON 형식으로만 작성하세요."
            p_prompt = f"""오늘 한국 주식시장 거래대금 상위 10종목과 그 기술적 지표(최근 1개월 기준)는 다음과 같습니다:

{context_str}

이 데이터를 바탕으로 다음 2가지를 분석해 주세요:
1. 시장 전체의 흐름과 주도 테마에 대한 전반적인 시황 분석 (마크다운 형식, 3~4문단)
2. 10개 종목 각각에 대한 냉철한 매매 의견(적극 매수, 매수, 관망, 매도 중 택 1), 합리적인 1개월 목표가(숫자), 손절가(숫자), 그리고 한 줄 핵심 근거(1~2문장).

반드시 아래 JSON 형식으로 응답하세요:
{{
  "overall_summary": "마크다운 형식의 시황 요약글...",
  "stock_analysis": [
    {{
      "code": "종목코드",
      "recommendation": "적극 매수, 매수, 관망, 매도 중 택 1",
      "target_price": 85000,
      "stop_loss": 75000,
      "reason": "최근 RSI 과열권 진입 및 단기 저항선 도달로 차익 실현 권고 등..."
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
                except Exception as e:
                    print(f"JSON Parse Error: {e}\n{text}")
                    ai_data = None
                
        return jsonify({
            'success': True,
            'top_stocks': top_stocks,
            'ai_report': ai_data
        })
    except Exception as e:
        print(f"Market Trend Error: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)})
