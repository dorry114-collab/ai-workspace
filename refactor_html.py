import re
import os

with open('templates/home.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Extract CSS
css_match = re.search(r'<style>(.*?)</style>', html, re.DOTALL)
if css_match:
    css_content = css_match.group(1).strip()
    # Add some CSS for the Favorites section and global loader
    css_content += """
/* Global Loader Overlay */
#globalLoader {
    position: fixed;
    top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(11, 14, 20, 0.9);
    z-index: 10000;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    backdrop-filter: blur(10px);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.3s ease;
}
#globalLoader.active {
    opacity: 1;
    pointer-events: auto;
}
.loader-spinner {
    width: 60px; height: 60px;
    border: 5px solid rgba(0, 240, 255, 0.2);
    border-top-color: var(--primary);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-bottom: 20px;
}
@keyframes spin { 100% { transform: rotate(360deg); } }
.loader-text {
    color: #fff;
    font-size: 1.2rem;
    font-weight: 600;
}

/* Favorites Pin Button */
.pin-btn {
    position: absolute;
    top: 15px;
    right: 15px;
    background: rgba(0,0,0,0.5);
    border: 1px solid rgba(255,255,255,0.2);
    color: #fff;
    border-radius: 50%;
    width: 35px;
    height: 35px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s;
    z-index: 10;
}
.pin-btn:hover { background: var(--primary); color: #000; }
.pin-btn.pinned { background: var(--primary); color: #000; border-color: var(--primary); }
"""
    os.makedirs('static/css', exist_ok=True)
    with open('static/css/style.css', 'w', encoding='utf-8') as f:
        f.write(css_content)

# Extract JS
js_match = re.search(r'<script>(.*?)</script>', html, re.DOTALL)
if js_match:
    js_content = js_match.group(1).strip()
    js_content += """

// Global Loader
function showGlobalLoader(text = "AI가 작업 중입니다...") {
    document.getElementById('globalLoaderText').innerText = text;
    document.getElementById('globalLoader').classList.add('active');
}
function hideGlobalLoader() {
    document.getElementById('globalLoader').classList.remove('active');
}

// Favorites Logic
function togglePin(event, cardId) {
    event.preventDefault();
    event.stopPropagation();
    let pins = JSON.parse(localStorage.getItem('pinnedApps') || '[]');
    if (pins.includes(cardId)) {
        pins = pins.filter(id => id !== cardId);
        showToast("즐겨찾기에서 제거되었습니다.");
    } else {
        pins.push(cardId);
        showToast("상단 즐겨찾기에 추가되었습니다.");
    }
    localStorage.setItem('pinnedApps', JSON.stringify(pins));
    renderFavorites();
    updatePinButtons();
}

function updatePinButtons() {
    let pins = JSON.parse(localStorage.getItem('pinnedApps') || '[]');
    document.querySelectorAll('.pin-btn').forEach(btn => {
        let cid = btn.getAttribute('data-id');
        if(pins.includes(cid)) {
            btn.classList.add('pinned');
            btn.innerHTML = '<i class="fa-solid fa-thumbtack"></i>';
        } else {
            btn.classList.remove('pinned');
            btn.innerHTML = '<i class="fa-solid fa-thumbtack" style="transform: rotate(45deg);"></i>';
        }
    });
}

function renderFavorites() {
    let pins = JSON.parse(localStorage.getItem('pinnedApps') || '[]');
    const favContainer = document.getElementById('favoritesContainer');
    const favSection = document.getElementById('favoritesSection');
    
    if (pins.length === 0) {
        favSection.style.display = 'none';
        return;
    }
    
    favSection.style.display = 'block';
    favContainer.innerHTML = '';
    
    pins.forEach(cid => {
        let originalCard = document.getElementById(cid);
        if(originalCard) {
            let clone = originalCard.cloneNode(true);
            // change the onclick for the clone's pin button to unpin
            let pinBtn = clone.querySelector('.pin-btn');
            pinBtn.onclick = (e) => togglePin(e, cid);
            favContainer.appendChild(clone);
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    updatePinButtons();
    renderFavorites();
});
"""
    os.makedirs('static/js', exist_ok=True)
    with open('static/js/main.js', 'w', encoding='utf-8') as f:
        f.write(js_content)

# Modify HTML
html = re.sub(r'<style>.*?</style>', '<link rel="stylesheet" href="/static/css/style.css">', html, flags=re.DOTALL)
html = re.sub(r'<script>(.*?)</script>', '<script src="/static/js/main.js"></script>', html, flags=re.DOTALL)

# Add Favorites Section right after the Search Filter
favorites_html = """
        <!-- Favorites Section -->
        <div id="favoritesSection" style="display: none; width: 100%;">
            <div class="section-title" style="border-left-color: var(--primary);">⭐ 즐겨찾기</div>
            <div class="cards" id="favoritesContainer"></div>
            <div class="section-divider"></div>
        </div>
"""
html = html.replace('<div class="section-title" style="border-left-color: #ffaa00;">로컬 스캐너 (맛집 / 카페 / 병원)</div>', favorites_html + '\n        <div class="section-title" style="border-left-color: #ffaa00;">로컬 스캐너 (맛집 / 카페 / 병원)</div>')

# Add IDs and Pin Buttons to all cards
# Find all <a href="..." class="card" data-type="...">
def card_replacer(match):
    full_match = match.group(0)
    href = match.group(1)
    # Generate an ID from href
    card_id = "card_" + href.replace("/", "").replace("_", "")
    
    # Insert id and pin button
    # full_match format: <a href="..." class="card" data-type="...">
    new_tag = full_match.replace('class="card"', f'id="{card_id}" class="card"')
    pin_btn = f'\n                <div class="pin-btn" data-id="{card_id}" onclick="togglePin(event, \'{card_id}\')"><i class="fa-solid fa-thumbtack" style="transform: rotate(45deg);"></i></div>'
    return new_tag + pin_btn

html = re.sub(r'<a href="([^"]+)" class="card"([^>]*)>', card_replacer, html)

# Add Global Loader
loader_html = """
    <!-- Global Loader -->
    <div id="globalLoader">
        <div class="loader-spinner"></div>
        <div class="loader-text" id="globalLoaderText">AI가 작업 중입니다...</div>
    </div>
"""
html = html.replace('</body>', loader_html + '\n</body>')

with open('templates/home.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("HTML, CSS, JS refactored successfully.")
