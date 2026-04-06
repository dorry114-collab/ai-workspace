import os
import uuid
import tempfile
import urllib.request
import base64
from io import BytesIO
import re
import math
import traceback

from gtts import gTTS
from PIL import Image as PILImage, ImageDraw, ImageFont

script = "안녕. 반가워. 이것은 테스트 대본이야."
images = ["https://image.pollinations.ai/prompt/cat?width=720&height=1280&nologo=true"]
bgm_url = ""

temp_dir = tempfile.mkdtemp()
print(f"Temp dir: {temp_dir}")

font_path = "static/NanumGothic.ttf"
try:
    pil_font = ImageFont.truetype(font_path, 40)
except:
    pil_font = ImageFont.load_default()

sentences = [s.strip() for s in re.split(r'[.?!|\n]+', script) if s.strip()]

from moviepy import ImageClip, AudioFileClip, CompositeAudioClip, concatenate_videoclips

clips = []
for i, text in enumerate(sentences):
    audio_path = os.path.join(temp_dir, f"audio_{i}.mp3")
    tts = gTTS(text=text, lang='ko', slow=False)
    tts.save(audio_path)
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration
    if duration < 1.0: duration = 1.0

    img_idx = math.floor((i / len(sentences)) * len(images))
    safe_img_idx = min(img_idx, len(images) - 1)
    img_src = images[safe_img_idx]

    img_file_path = os.path.join(temp_dir, f"img_{i}_{safe_img_idx}.png")
    
    if img_src.startswith('data:image'):
        header, encoded = img_src.split(',', 1)
        img_data = base64.b64decode(encoded)
        pil_img = PILImage.open(BytesIO(img_data)).convert('RGB')
    else:
        req = urllib.request.Request(img_src, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            pil_img = PILImage.open(BytesIO(response.read())).convert('RGB')

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
    
    pil_img = pil_img.resize((target_w, target_h), PILImage.Resampling.LANCZOS)
    
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

final_video = concatenate_videoclips(clips, method="compose")
final_video.write_videofile("/tmp/test_out.mp4", fps=24, codec="libx264", audio_codec="aac", logger=None)
print("SUCCESS!")
