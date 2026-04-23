import re
import os

with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

def extract_block(start_line, end_line):
    return "".join(lines[start_line-1:end_line-1])

# Global imports (lines 1 to 28)
global_imports = extract_block(1, 29)
global_imports += "from flask import Blueprint, render_template, request, jsonify\n"
global_imports += "import os, json, datetime, uuid, urllib.parse, urllib.request, traceback\n"
global_imports += "from extensions import db, limiter\n"

# Helpers
stock_helpers = extract_block(30, 50)
yt_helpers = extract_block(277, 394)
prompt_helpers = extract_block(405, 532)
stats_helpers = extract_block(628, 661)

# Now, mapping of routes to blueprints
# For each route, I need to replace `@app.route` with `@<blueprint>.route`
def make_blueprint(name, helper_blocks, route_ranges):
    content = global_imports + "\n"
    content += f"{name}_bp = Blueprint('{name}', __name__)\n\n"
    
    for hb in helper_blocks:
        content += hb + "\n"
        
    for start, end in route_ranges:
        block = extract_block(start, end)
        block = block.replace("@app.route", f"@{name}_bp.route")
        content += block + "\n"
        
    return content

# Define route boundaries
routes = [
    (50, 277, 'stock'), # api/stock
    (394, 405, 'tools'), # api/extract
    (532, 591, 'tools'), # api/prompt/ask
    (591, 628, 'tools'), # api/prompt/generate
    (661, 666, 'core'), # /
    (666, 702, 'core'), # api/comments
    (702, 706, 'scanner'), # restaurant
    (706, 710, 'tools'), # youtube
    (710, 714, 'tools'), # youtube_summary
    (714, 882, 'tools'), # api/youtube/summary
    (882, 919, 'tools'), # api/youtube/chat
    (919, 923, 'stock'), # stock
    (923, 927, 'tools'), # prompt
    (927, 931, 'tools'), # lotto
    (931, 984, 'tools'), # api/lotto
    (984, 988, 'tools'), # shorts
    (988, 992, 'games_life'), # novel
    (992, 1050, 'games_life'), # api/novel/chat
    (1050, 1054, 'tools'), # english
    (1054, 1113, 'tools'), # api/english/chat
    (1113, 1155, 'tools'), # api/english/hint
    (1155, 1193, 'tools'), # api/english/tts
    (1193, 1229, 'tools'), # api/shorts/prompts
    (1229, 1254, 'tools'), # api/shorts/export
    (1254, 1488, 'tools'), # api/shorts/status
    (1488, 1634, 'scanner'), # api/restaurant/search
    (1634, 1658, 'scanner'), # api/geocode
    (1658, 1735, 'scanner'), # api/restaurant/summary
    (1735, 1803, 'scanner'), # api/restaurant/chat
    (1803, 1807, 'scanner'), # bakery
    (1807, 1949, 'scanner'), # api/bakery/search
    (1949, 1953, 'scanner'), # cafe
    (1953, 2093, 'scanner'), # api/cafe/search
    (2093, 2097, 'scanner'), # clinic
    (2097, 2260, 'scanner'), # api/clinic/search
    (2260, 2331, 'tools'), # api/shorts/script/ask
    (2331, 2387, 'tools'), # api/shorts/script/generate
    (2387, 2391, 'games_life'), # game_office
    (2391, 2395, 'games_life'), # tarot
    (2395, 2399, 'games_life'), # saju
    (2399, 2403, 'games_life'), # archive
    (2403, 2442, 'games_life'), # api/tarot/draw
    (2442, 2484, 'games_life'), # api/saju/analyze
    (2484, 2488, 'tools'), # shopping
    (2488, 2555, 'tools'), # api/shopping/analyze
    (2555, 2559, 'games_life'), # face
    (2559, 2612, 'games_life'), # api/face/analyze
    (2612, 2616, 'games_life'), # dream
    (2616, 2639, 'games_life'), # api/dream/analyze
    (2639, 2642, 'tools'), # chef
    (2642, 2659, 'tools'), # api/chef/recipe
    (2659, 2662, 'games_life'), # therapist
    (2662, 2676, 'games_life'), # api/therapist/counsel
    (2676, 2679, 'tools'), # polisher
    (2679, 2691, 'tools'), # api/polisher/convert
    (2691, 2694, 'games_life'), # fashion
    (2694, 2714, 'games_life'), # api/fashion/evaluate
    (2714, 2717, 'games_life'), # love
    (2717, 2738, 'games_life'), # api/love/analyze
    (2738, 2741, 'games_life'), # diet
    (2741, 2762, 'games_life'), # api/diet/analyze
    (2762, 2765, 'games_life'), # diary
    (2765, 2787, 'games_life'), # api/diary/chat
    (2787, 2809, 'games_life'), # api/diary/compile
    (2809, len(lines)+1, 'games_life'), # api/diary/notion
]

blueprints = {
    'core': {'helpers': [stats_helpers], 'ranges': []},
    'stock': {'helpers': [stock_helpers, prompt_helpers], 'ranges': []},
    'tools': {'helpers': [yt_helpers, prompt_helpers], 'ranges': []},
    'scanner': {'helpers': [], 'ranges': []},
    'games_life': {'helpers': [], 'ranges': []}
}

for start, end, bp in routes:
    blueprints[bp]['ranges'].append((start, end))

for bp_name, data in blueprints.items():
    content = make_blueprint(bp_name, data['helpers'], data['ranges'])
    # Fix global variable issues
    content = content.replace("global GROQ_MODEL_CACHE", "")
    with open(f"routes/{bp_name}.py", "w", encoding="utf-8") as f:
        f.write(content)

print("Split completed successfully.")
