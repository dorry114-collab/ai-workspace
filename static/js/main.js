window.dataLayer = window.dataLayer || [];
      function gtag(){dataLayer.push(arguments);}
      gtag('js', new Date());
      gtag('config', 'G-EVBPHWZ6FK');

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

// Search Filter Logic
function filterApps() {
    const query = document.getElementById('appSearchInput').value.toLowerCase();
    const cards = document.querySelectorAll('.cards:not(#favoritesContainer) > .card');
    
    cards.forEach(card => {
        const title = card.querySelector('h2').innerText.toLowerCase();
        const desc = card.querySelector('.description').innerText.toLowerCase();
        
        if (title.includes(query) || desc.includes(query)) {
            card.style.display = 'block';
        } else {
            card.style.display = 'none';
        }
    });

    // 검색 중일 때는 전체보기 탭으로 시각적 초기화
    if(query.trim() !== '') {
        document.querySelectorAll('.cat-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelector('.cat-btn[data-category="all"]').classList.add('active');
    }
}

// Category Filter Logic
function filterCategory(category) {
    // 탭 활성화 스타일 변경
    document.querySelectorAll('.cat-btn').forEach(btn => {
        if(btn.getAttribute('data-category') === category) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // 탭 이동 시 검색어 초기화
    document.getElementById('appSearchInput').value = '';

    const cards = document.querySelectorAll('.cards:not(#favoritesContainer) > .card');
    
    const localTypes = ['restaurant', 'bakery', 'cafe', 'clinic'];
    const utilityTypes = ['english', 'shopping', 'shorts', 'youtube', 'stock', 'prompt', 'lotto', 'tool'];

    cards.forEach(card => {
        if (category === 'all') {
            card.style.display = 'block';
            return;
        }
        
        const type = card.getAttribute('data-type');
        let match = false;
        
        if (category === 'local' && localTypes.includes(type)) match = true;
        if (category === 'utility' && utilityTypes.includes(type)) match = true;
        if (category === 'game' && type === 'game') match = true;
        if (category === 'life' && type === 'life') match = true;
        
        if (match) {
            card.style.display = 'block';
        } else {
            card.style.display = 'none';
        }
    });
}

// Global Viral Share Logic (Web Share API)
function shareResult(title, text, url) {
    if (navigator.share) {
        navigator.share({
            title: title,
            text: text,
            url: url || window.location.href
        }).then(() => {
            console.log('Thanks for sharing!');
        }).catch(console.error);
    } else {
        // Fallback: Copy to clipboard
        navigator.clipboard.writeText(url || window.location.href).then(() => {
            alert('링크가 클립보드에 복사되었습니다! 친구들에게 공유해보세요.');
        }).catch(err => {
            console.error('Failed to copy: ', err);
            alert('공유하기를 지원하지 않는 브라우저입니다.');
        });
    }
}

// PWA Install Prompt Logic
let deferredPrompt;
window.addEventListener('beforeinstallprompt', (e) => {
    // Prevent the mini-infobar from appearing on mobile
    e.preventDefault();
    // Stash the event so it can be triggered later.
    deferredPrompt = e;
    
    // Show the install banner if it exists
    const installBanner = document.getElementById('installBanner');
    if (installBanner) {
        installBanner.style.display = 'flex';
        
        installBanner.addEventListener('click', async () => {
            if (deferredPrompt) {
                // Show the install prompt
                deferredPrompt.prompt();
                // Wait for the user to respond to the prompt
                const { outcome } = await deferredPrompt.userChoice;
                console.log(`User response to the install prompt: ${outcome}`);
                // We've used the prompt, and can't use it again, throw it away
                deferredPrompt = null;
                installBanner.style.display = 'none';
            }
        });
    }
});

// Hide banner if app is already installed
window.addEventListener('appinstalled', () => {
    const installBanner = document.getElementById('installBanner');
    if (installBanner) installBanner.style.display = 'none';
    deferredPrompt = null;
    console.log('PWA was installed');
});
