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

tools_bp = Blueprint('tools', __name__)

# --- YOUTUBE EXTRACTOR LOGIC ---
def extract_channel_videos(channel_input, limit=50, sort='views'):
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
                search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={channel_id}&maxResults={q_limit}&order={'date' if sort == 'date' else 'viewCount'}&type=video&key={api_key}"
                
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
            
        # 3. Get exact statistics + snippet for sorting (Batch API accepts max 50 per request)
        stats_data_items = []
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i+50]
            stats_url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id={','.join(chunk)}&key={api_key}"
            stats_resp = requests.get(stats_url)
            s_data = stats_resp.json()
            if 'items' in s_data:
                stats_data_items.extend(s_data['items'])
        
        results = []
        for item in stats_data_items:
            v_id = item['id']
            views = int(item['statistics'].get('viewCount', 0))
            published_at = item.get('snippet', {}).get('publishedAt', '')
            results.append({
                'id': v_id,
                'title': video_titles.get(v_id, 'No Title'),
                'url': f"https://www.youtube.com/watch?v={v_id}",
                'view_count': views,
                'published_at': published_at
            })
            
        # 4. Sort by selected criterion
        if sort == 'date':
            results.sort(key=lambda x: x.get('published_at', ''), reverse=True)
        else:
            results.sort(key=lambda x: x['view_count'], reverse=True)
            
        return {"success": True, "data": results[:limit], "channel": channel_input, "is_search": is_search_query}
        
    except Exception as e:
        return {"success": False, "error": f"유튜브 통신 중 서버 오류가 발생했습니다: {str(e)}"}


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


@tools_bp.route('/api/extract', methods=['POST'])
def extract():
    data = request.json
    channel_id = data.get('channel_id')
    limit = int(data.get('limit', 50))
    sort = data.get('sort', 'views')  # 'views' or 'date'
    if not channel_id:
        return jsonify({"success": False, "error": "채널명을 입력해주세요."})
    
    result = extract_channel_videos(channel_id, limit, sort)
    return jsonify(result)


@tools_bp.route('/api/prompt/ask', methods=['POST'])
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


@tools_bp.route('/api/prompt/generate', methods=['POST'])
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


@tools_bp.route('/youtube')
def youtube():
    return render_template('youtube.html')


@tools_bp.route('/youtube_summary')
def youtube_summary():
    return render_template('youtube_summary.html')


@tools_bp.route('/api/youtube/summary', methods=['POST'])
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



@tools_bp.route('/api/youtube/chat', methods=['POST'])
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


@tools_bp.route('/prompt')
def prompt():
    return render_template('prompt.html')


@tools_bp.route('/lotto')
def lotto():
    return render_template('lotto.html')


@tools_bp.route('/api/lotto', methods=['GET'])
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



@tools_bp.route('/shorts')
def shorts_maker():
    return render_template('shorts_maker.html')


@tools_bp.route('/english')
def english_tutor():
    return render_template('english_tutor.html')


@tools_bp.route('/api/english/chat', methods=['POST'])
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


@tools_bp.route('/api/english/hint', methods=['POST'])
def api_english_hint():
    data = request.json
    messages = data.get('messages', [])
    
    gemini_api_key = os.environ.get('GEMINI_API_KEY')
    if not gemini_api_key:
        return jsonify({"success": False, "error": "[필수] API 키가 없습니다."})
        
    if not messages:
        return jsonify({"success": False, "error": "메시지 내역이 없습니다."})
        
    hint_prompt = """Based on the previous conversation history, provide exactly 3 natural English responses the user could say right now to continue the roleplay. Output ONLY valid JSON in this format:
{"hints": ["Response option 1", "Response option 2", "Response option 3"]}"""

    hint_messages = []
    # Copy conversation but only keep user/assistant roles, discard system prompt to save token, 
    # then append the new hint instruction
    for msg in messages:
        if msg.get('role') in ['user', 'assistant']:
            hint_messages.append({"role": msg['role'], "content": msg['content']})
            
    hint_messages.append({"role": "user", "content": hint_prompt})
    
    success, result_text = _call_gemini_chat(gemini_api_key, hint_messages, temperature=0.7)
    
    if success:
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()
            
        try:
            import json
            parsed = json.loads(result_text)
            return jsonify({"success": True, "hints": parsed.get('hints', [])})
        except Exception as e:
            return jsonify({"success": False, "error": f"JSON 파싱 실패: {str(e)} | 원본: {result_text}"})
    else:
        return jsonify({"success": False, "error": result_text})



@tools_bp.route('/api/english/tts', methods=['POST'])
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


@tools_bp.route('/api/shorts/prompts', methods=['POST'])
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


@tools_bp.route('/api/shorts/export', methods=['POST'])
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


@tools_bp.route('/api/shorts/status/<job_id>', methods=['GET'])
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


@tools_bp.route('/api/shorts/script/ask', methods=['POST'])
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


@tools_bp.route('/api/shorts/script/generate', methods=['POST'])
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


@tools_bp.route('/shopping')
def shopping():
    return render_template('shopping.html')


@tools_bp.route('/api/shopping/analyze', methods=['POST'])
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


@tools_bp.route('/chef')
def chef_view(): return render_template('chef.html')


@tools_bp.route('/api/chef/recipe', methods=['POST'])
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


@tools_bp.route('/polisher')
def polisher_view(): return render_template('polisher.html')


@tools_bp.route('/api/polisher/convert', methods=['POST'])
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


@tools_bp.route('/message')
def message_maker_view():
    return render_template('message_maker.html')


@tools_bp.route('/api/message/generate', methods=['POST'])
def api_message_generate():
    data = request.json
    target = data.get('target', '부모님')
    context = data.get('context', '')
    
    if not context:
        return jsonify({"success": False, "error": "전달할 내용을 입력해주세요."})
        
    api_key = os.environ.get('GEMINI_API_KEY')
    groq_api_key = os.environ.get('GROQ_API_KEY')
    
    if not api_key and not groq_api_key:
        return jsonify({"success": False, "error": "API 키가 설정되지 않았습니다."})
        
    sys_prompt = f"""당신은 세계 최고의 메세지/카카오톡 대필 전문가입니다.
사용자가 대충 적은 상황(context)을 보고, 받는 대상({target})에게 보내기 딱 좋은 찰떡같은 메세지 3가지 버전을 작성해주세요.

받는 사람(대상): {target}
사용자의 상황(초안): {context}

[핵심 규칙]
1. 절대 과하게 오글거리거나 인위적인 문장은 쓰지 마세요. 한국인들이 카카오톡에서 실제로 쓰는 매우 자연스럽고 일상적인 말투(구어체)를 완벽하게 반영하세요.
2. 장황하게 길게 쓰면 부담스럽습니다. 핵심만 간결하고 깔끔하게 전달하세요.
3. 대상과의 관계를 고려하여 서로 다른 뉘앙스(예: 담백한 톤, 살짝 애교/유머 있는 톤, 조금 더 정중한 톤 등) 3가지를 만들어주세요.
4. 이모티콘(이모지)은 너무 남발하지 말고, 한두 개만 적절히 포인트로 넣어주세요.

반드시 다음 JSON 형식으로만 응답하세요. 다른 말은 절대 넣지 마세요.
{{
    "options": [
        {{ "style": "톤 이름 (예: 정중하고 진지한 스타일)", "text": "실제 메시지 내용" }},
        {{ "style": "톤 이름 (예: 애교 섞인 귀여운 스타일)", "text": "실제 메시지 내용" }},
        {{ "style": "톤 이름 (예: 짧고 담백한 스타일)", "text": "실제 메시지 내용" }}
    ]
}}
"""
    success = False
    result_text = ""
    
    if api_key:
        success, result_text = _call_gemini_chat(api_key, [{"role": "user", "content": sys_prompt}], temperature=0.7)
        if not success and ("429" in result_text or "exceeded" in result_text.lower()) and groq_api_key:
            success, result_text = _call_groq_chat(groq_api_key, [{"role": "user", "content": sys_prompt}], temperature=0.7)
    elif groq_api_key:
        success, result_text = _call_groq_chat(groq_api_key, [{"role": "user", "content": sys_prompt}], temperature=0.7)
        
    if not success:
        return jsonify({"success": False, "error": f"AI 통신 오류: {result_text}"})
        
    # JSON 파싱
    if "```json" in result_text:
        result_text = result_text.split("```json")[1].split("```")[0].strip()
    elif "```" in result_text:
        result_text = result_text.split("```")[1].split("```")[0].strip()
        
    try:
        import json
        parsed = json.loads(result_text)
        return jsonify({"success": True, "options": parsed.get('options', [])})
    except Exception as e:
        return jsonify({"success": False, "error": f"JSON 형식 오류: {str(e)}\n\n원본 응답: {result_text}"})


@tools_bp.route('/travel')
def travel_planner_view():
    return render_template('travel_planner.html')


@tools_bp.route('/api/travel/plan', methods=['POST'])
def api_travel_plan():
    data = request.json
    destination = data.get('destination', '')
    duration = data.get('duration', '')
    companion = data.get('companion', '')
    themes = data.get('themes', [])
    draft_schedule = data.get('draft_schedule', '').strip()
    
    if not destination:
        return jsonify({"success": False, "error": "목적지를 입력해주세요."})
        
    api_key = os.environ.get('GEMINI_API_KEY')
    groq_api_key = os.environ.get('GROQ_API_KEY')
    
    if not api_key and not groq_api_key:
        return jsonify({"success": False, "error": "API 키가 설정되지 않았습니다."})
        
    theme_str = ", ".join(themes)
    
    user_draft_text = f"\n[사용자의 기존 여행 계획 (초안)]\n{draft_schedule}\n(주의: 위 초안에 적힌 날짜와 시간, 장소는 반드시! 그대로 유지하고 비어있는 시간이나 세부 설명만 채워주세요.)\n" if draft_schedule else ""
    
    sys_prompt = f"""당신은 세계 최고의 여행 가이드이자 여행 플래너입니다.
사용자가 입력한 목적지, 일정, 동반자, 테마를 바탕으로 완벽한 세부 일정을 기획해야 합니다.
국내 여행 뿐만 아니라 해외 여행의 경우에도 현지의 유명 랜드마크, 맛집, 동선을 정확하게 고려하여 일정을 짜주세요.

[입력 정보]
- 목적지: {destination}
- 기간: {duration}
- 동반자: {companion}
- 핵심 테마: {theme_str}
{user_draft_text}

[출력 JSON 구조 - 반드시 이 구조를 지키세요]
{{
  "destination": "{destination}",
  "budget_tips": [
    "예상 경비나 환전/결제 관련 팁 1 (구체적인 금액이나 수단 언급)",
    "경비 팁 2"
  ],
  "packing_tips": [
    "해당 목적지와 기간에 맞는 필수 준비물 1",
    "준비물 팁 2"
  ],
  "days": [
    {{
      "day_number": 1,
      "theme": "1일차 핵심 테마 (예: 현지 도착 및 야경 투어)",
      "schedule": [
        {{
          "time": "14:00 - 15:30",
          "place_name": "구체적인 장소 이름 (예: 센소지, 신주쿠 교엔, 오설록 티 뮤지엄 등)",
          "description": "이곳에 가야 하는 이유와 즐길 거리, 메뉴 추천 등 상세한 설명"
        }}
      ]
    }}
  ]
}}

[요구사항]
1. 장소 이름(place_name)은 추후 구글 지도 검색에 용이하도록 정확한 고유 명사(현지어 또는 널리 쓰이는 한국어 명칭)로 적어주세요.
2. 각 Day마다 아침부터 밤까지 일정이 꽉 차지만 물리적으로 이동 가능한 현실적인 동선이어야 합니다.
3. {theme_str} 테마가 적극적으로 반영되어야 합니다.
4. 반드시 마크다운(```json) 없이 순수 JSON 문자열만 응답하세요. 다른 설명은 붙이지 마세요.
"""
    success = False
    result_text = ""
    
    if api_key:
        success, result_text = _call_gemini_chat(api_key, [{"role": "user", "content": sys_prompt}], temperature=0.7)
        if not success and ("429" in result_text or "exceeded" in result_text.lower()) and groq_api_key:
            success, result_text = _call_groq_chat(groq_api_key, [{"role": "user", "content": sys_prompt}], temperature=0.7)
    elif groq_api_key:
        success, result_text = _call_groq_chat(groq_api_key, [{"role": "user", "content": sys_prompt}], temperature=0.7)
        
    if not success:
        return jsonify({"success": False, "error": f"AI 통신 오류: {result_text}"})
        
    # JSON 파싱
    if "```json" in result_text:
        result_text = result_text.split("```json")[1].split("```")[0].strip()
    elif "```" in result_text:
        result_text = result_text.split("```")[1].split("```")[0].strip()
        
    try:
        import json
        parsed = json.loads(result_text)
        return jsonify({"success": True, "plan": parsed})
    except Exception as e:
        return jsonify({"success": False, "error": f"JSON 형식 오류: {str(e)}\n\n원본 응답: {result_text}"})

@tools_bp.route('/meetup')
def meetup_planner_view():
    return render_template('meetup.html', google_maps_api_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))


@tools_bp.route('/api/meetup/recommend', methods=['POST'])
def api_meetup_recommend():
    data = request.json
    addresses = data.get('addresses', [])
    
    if not addresses or len(addresses) < 2:
        return jsonify({"success": False, "error": "최소 2개 이상의 출발 주소를 입력해주세요."})
        
    kakao_api_key = os.environ.get('KAKAO_REST_API_KEY')
    if not kakao_api_key:
        return jsonify({"success": False, "error": "Kakao API 키가 설정되지 않았습니다."})
        
    import urllib.parse
    import requests
    import math
    
    headers = {"Authorization": f"KakaoAK {kakao_api_key}"}
    
    locations = []
    
    # 1. Geocode all addresses
    for addr in addresses:
        if not addr.strip(): continue
        geo_url = f"https://dapi.kakao.com/v2/local/search/address.json?query={urllib.parse.quote(addr.strip())}"
        resp = requests.get(geo_url, headers=headers).json()
        
        if resp.get('documents'):
            doc = resp['documents'][0]
            locations.append({
                "original": addr.strip(),
                "name": doc.get('address_name', addr),
                "lat": float(doc['y']),
                "lng": float(doc['x'])
            })
        else:
            # Fallback to keyword search
            kw_url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={urllib.parse.quote(addr.strip())}"
            resp_kw = requests.get(kw_url, headers=headers).json()
            if resp_kw.get('documents'):
                doc = resp_kw['documents'][0]
                locations.append({
                    "original": addr.strip(),
                    "name": doc.get('place_name', addr),
                    "lat": float(doc['y']),
                    "lng": float(doc['x'])
                })
            else:
                return jsonify({"success": False, "error": f"주소를 찾을 수 없습니다: {addr}"})
                
    if len(locations) < 2:
         return jsonify({"success": False, "error": "유효한 주소가 2개 이상 필요합니다."})
         
    # 2. Calculate Midpoint (Average of lat/lng)
    avg_lat = sum(loc['lat'] for loc in locations) / len(locations)
    avg_lng = sum(loc['lng'] for loc in locations) / len(locations)
    
    # 3. Get address for Midpoint
    coord_url = f"https://dapi.kakao.com/v2/local/geo/coord2address.json?x={avg_lng}&y={avg_lat}"
    coord_resp = requests.get(coord_url, headers=headers).json()
    midpoint_address = "중간 지점"
    if coord_resp.get('documents'):
        doc = coord_resp['documents'][0]
        if doc.get('road_address'):
            midpoint_address = doc['road_address']['address_name']
        elif doc.get('address'):
            midpoint_address = doc['address']['address_name']
            
    # 4. Find places around midpoint (FD6 - Food, CE7 - Cafe)
    places = []
    for category in ['FD6', 'CE7']:
        cat_url = f"https://dapi.kakao.com/v2/local/search/category.json?category_group_code={category}&x={avg_lng}&y={avg_lat}&radius=2000&sort=distance"
        cat_resp = requests.get(cat_url, headers=headers).json()
        if cat_resp.get('documents'):
             for p in cat_resp['documents'][:15]: # Take top 15 from each
                 places.append({
                     "name": p['place_name'],
                     "category": p['category_name'],
                     "address": p.get('road_address_name') or p.get('address_name') or "",
                     "distance": p['distance'],
                     "url": p['place_url']
                 })
                 
    if not places:
        return jsonify({"success": False, "error": "중간 지점 근처에 추천할 만한 식당이나 카페를 찾지 못했습니다."})
        
    # 5. AI Curation via Gemini
    ai_api_key = os.environ.get('GEMINI_API_KEY')
    if not ai_api_key:
         return jsonify({"success": False, "error": "AI API 키가 설정되지 않았습니다."})
         
    places_text = ""
    for idx, p in enumerate(places):
        places_text += f"{idx+1}. {p['name']} ({p['category']}) - {p['distance']}m 거리 / 주소: {p['address']}\n"
        
    sys_prompt = f"""당신은 친구들의 약속 장소를 정해주는 AI 매니저입니다.
다수의 사람들이 모이는 중간 지점 근처의 장소 데이터가 주어집니다.
친구들이 모여서 식사하거나 차를 마시기 가장 좋은 장소 5곳을 선별해주세요. (카페와 식당을 골고루 섞어주세요)

[중간 지점 정보]
- 위도: {avg_lat}, 경도: {avg_lng}
- 행정구역: {midpoint_address}

[주변 후보 리스트]
{places_text}

[출력 형식 - 반드시 JSON 구조만 출력하세요]
{{
  "midpoint": {{
    "lat": {avg_lat},
    "lng": {avg_lng},
    "address": "{midpoint_address}"
  }},
  "recommendations": [
    {{
      "name": "장소 이름",
      "category": "분류 (예: 카페, 고깃집 등)",
      "distance": "거리 (문자열로, 예: '500m')",
      "reason": "약속 장소로 추천하는 이유 (친근한 말투로 1~2문장)"
    }}
  ]
}}
"""
    
    success, result_text = _call_gemini_chat(ai_api_key, [{"role": "user", "content": sys_prompt}], temperature=0.7)
    
    if not success:
         return jsonify({"success": False, "error": f"AI 추천 중 오류가 발생했습니다: {result_text}"})
         
    if "```json" in result_text:
        result_text = result_text.split("```json")[1].split("```")[0].strip()
    elif "```" in result_text:
        result_text = result_text.split("```")[1].split("```")[0].strip()
        
    try:
        import json
        parsed = json.loads(result_text)
        return jsonify({
            "success": True, 
            "midpoint": parsed.get("midpoint", {"lat": avg_lat, "lng": avg_lng, "address": midpoint_address}),
            "recommendations": parsed.get("recommendations", []),
            "locations": locations
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"JSON 파싱 오류: {str(e)}\n\n원본 응답: {result_text}"})

@tools_bp.route('/survival_test')
def survival_test_view():
    return render_template('viral_test.html')


# ─────────────────────────────────────────────
# 카카오톡 답장 추천기
# ─────────────────────────────────────────────
@tools_bp.route('/kakao_reply')
def kakao_reply_view():
    return render_template('kakao_reply.html')


@tools_bp.route('/api/kakao/reply', methods=['POST'])
def api_kakao_reply():
    import base64, json, traceback
    import google.generativeai as genai

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({'success': False, 'error': 'GEMINI_API_KEY가 설정되지 않았습니다.'})

    if 'image' not in request.files:
        return jsonify({'success': False, 'error': '이미지 파일이 없습니다.'})

    image_file = request.files['image']
    context_text = request.form.get('context', '').strip()
    tones_raw = request.form.get('tones', '[]')

    try:
        tones = json.loads(tones_raw)
    except:
        tones = ['친근하게', '쿨하게', '유머있게', '따뜻하게']

    if not tones:
        tones = ['친근하게', '쿨하게', '유머있게', '따뜻하게']

    try:
        image_bytes = image_file.read()
        mime_type = image_file.mimetype or 'image/jpeg'

        # Gemini Vision 호출
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')

        tones_str = ', '.join(tones)
        context_part = f'\n추가 상황 정보: {context_text}' if context_text else ''

        prompt = f"""당신은 대화 맥락 분석과 소셜 커뮤니케이션 전문가입니다.

위 이미지는 카카오톡 대화 캡처입니다. 다음을 수행해 주세요:

1. 대화 맥락 파악: 누가 누구에게 무슨 말을 했는지, 대화의 흐름과 분위기를 파악하세요.
2. 마지막 메시지에 대한 적절한 답장을 아래 분위기별로 각 1개씩 생성하세요: {tones_str}{context_part}

**중요 규칙:**
- 답장은 반드시 한국어로 작성하세요
- 카카오톡에서 실제로 보낼 수 있는 자연스러운 문체로 작성하세요
- 각 분위기에 맞게 확실히 다른 느낌으로 작성하세요
- 너무 길지 않게 (3~5문장 이내)

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요:
{{
  "summary": "AI가 파악한 대화 맥락 요약 (2~3문장, 예: 'A가 B에게 주말 약속을 제안하는 상황입니다. 마지막으로 B가...')",
  "replies": [
    {{"tone": "{tones[0] if tones else '친근하게'}", "text": "답장 내용"}},
    {{"tone": "{tones[1] if len(tones) > 1 else '쿨하게'}", "text": "답장 내용"}}
  ]
}}"""

        image_part = {
            'mime_type': mime_type,
            'data': base64.b64encode(image_bytes).decode('utf-8')
        }

        response = model.generate_content(
            [image_part, prompt],
            generation_config=genai.types.GenerationConfig(temperature=0.8)
        )
        result_text = response.text.strip()

        # JSON 파싱
        if '```json' in result_text:
            result_text = result_text.split('```json')[1].split('```')[0].strip()
        elif '```' in result_text:
            result_text = result_text.split('```')[1].split('```')[0].strip()

        parsed = json.loads(result_text)

        # 선택한 톤 수만큼 replies 보장
        replies = parsed.get('replies', [])
        # 혹시 톤 수가 부족하면 있는 것만 반환
        return jsonify({
            'success': True,
            'summary': parsed.get('summary', ''),
            'replies': replies
        })


    except json.JSONDecodeError as je:
        return jsonify({'success': False, 'error': f'AI 응답 파싱 오류입니다. 다시 시도해주세요.'})
    except Exception as e:
        print(f"Kakao Reply Error: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'분석 중 오류가 발생했습니다: {str(e)}'})


# ═══════════════════════════════════════════════════════════════
#  통합 앱 라우트 (8개 그룹 통합)
# ═══════════════════════════════════════════════════════════════

from flask import redirect

# ── 1. 🗺️ AI 동네 탐색기 (restaurant + cafe + bakery + clinic)
@tools_bp.route('/local')
def local_view():
    google_maps_api_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')
    return render_template('local.html', google_maps_api_key=google_maps_api_key)

# ── 2. 📍 AI 종합 플래너 (travel + course + meetup)
@tools_bp.route('/planner')
def planner_view():
    google_maps_api_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')
    return render_template('planner.html', google_maps_api_key=google_maps_api_key)

# ── 3. 🎥 AI 유튜브 스튜디오 (youtube + youtube_summary)
@tools_bp.route('/youtube_studio')
def youtube_studio_view():
    return render_template('youtube_studio.html')

# ── 4. 📈 AI 주식 분석기 (market + stock)
@tools_bp.route('/invest')
def invest_view():
    return render_template('invest.html')

# ── 5. 💬 AI 메시지 마스터 (kakao_reply + message + polisher)
@tools_bp.route('/message_hub')
def message_hub_view():
    return render_template('message_hub.html')

# ── 6. 🔮 AI 운세 종합관 (saju + tarot + dream)
@tools_bp.route('/mystic')
def mystic_view():
    return render_template('mystic.html')

# ── 7. 🥗 AI 건강 코치 (diet + chef)
@tools_bp.route('/health')
def health_view():
    return render_template('health.html')

# ── 8. 👁️ AI 비주얼 분석 (face + fashion)
@tools_bp.route('/vision_ai')
def vision_ai_view():
    return render_template('vision_ai.html')


# ═══════════════════════════════════════════════════════════════
#  기존 URL → 새 URL Redirect (북마크/공유 링크 보호)
# ═══════════════════════════════════════════════════════════════

# 로컬 탐색기 redirects
@tools_bp.route('/restaurant')
def redirect_restaurant():
    return redirect('/local?tab=restaurant', code=301)

@tools_bp.route('/cafe')
def redirect_cafe():
    return redirect('/local?tab=cafe', code=301)

@tools_bp.route('/bakery')
def redirect_bakery():
    return redirect('/local?tab=cafe', code=301)

@tools_bp.route('/clinic')
def redirect_clinic():
    return redirect('/local?tab=clinic', code=301)

# 플래너 redirects
@tools_bp.route('/travel')
def redirect_travel():
    return redirect('/planner?tab=travel', code=301)

@tools_bp.route('/course')
def redirect_course():
    return redirect('/planner?tab=course', code=301)

@tools_bp.route('/meetup')
def redirect_meetup():
    return redirect('/planner?tab=meetup', code=301)

# 유튜브 스튜디오 redirects
@tools_bp.route('/youtube')
def redirect_youtube():
    return redirect('/youtube_studio?tab=extract', code=301)

@tools_bp.route('/youtube_summary')
def redirect_youtube_summary():
    return redirect('/youtube_studio?tab=summary', code=301)

# 주식 분석기 redirects
@tools_bp.route('/market')
def redirect_market():
    return redirect('/invest?tab=market', code=301)

@tools_bp.route('/stock')
def redirect_stock():
    return redirect('/invest?tab=stock', code=301)

# 메시지 마스터 redirects
@tools_bp.route('/kakao_reply')
def redirect_kakao_reply():
    return redirect('/message_hub?tab=kakao', code=301)

@tools_bp.route('/message')
def redirect_message():
    return redirect('/message_hub?tab=maker', code=301)

@tools_bp.route('/polisher')
def redirect_polisher():
    return redirect('/message_hub?tab=polisher', code=301)

# 운세 종합관 redirects
@tools_bp.route('/saju')
def redirect_saju():
    return redirect('/mystic?tab=saju', code=301)

@tools_bp.route('/tarot')
def redirect_tarot():
    return redirect('/mystic?tab=tarot', code=301)

@tools_bp.route('/dream')
def redirect_dream():
    return redirect('/mystic?tab=dream', code=301)

# 건강 코치 redirects
@tools_bp.route('/diet')
def redirect_diet():
    return redirect('/health?tab=diet', code=301)

@tools_bp.route('/chef')
def redirect_chef():
    return redirect('/health?tab=chef', code=301)

# 비주얼 분석 redirects
@tools_bp.route('/face')
def redirect_face():
    return redirect('/vision_ai?tab=face', code=301)

@tools_bp.route('/fashion')
def redirect_fashion():
    return redirect('/vision_ai?tab=fashion', code=301)


