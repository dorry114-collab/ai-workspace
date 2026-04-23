import re

files = [
    'templates/face.html',
    'templates/fashion.html'
]

html_to_inject = """
            <div style="display: flex; gap: 10px; margin-bottom: 1rem; justify-content: center;">
                <button type="button" onclick="document.getElementById('imageInput').click()" style="background: rgba(255,255,255,0.1); border: 1px solid var(--border-color); color: var(--text-main); padding: 10px 20px; border-radius: 8px; cursor: pointer; flex: 1;"><i class="fa-solid fa-upload"></i> 파일 업로드</button>
                <button type="button" onclick="startCamera()" style="background: rgba(212,175,55,0.2); border: 1px solid var(--primary); color: var(--primary); padding: 10px 20px; border-radius: 8px; cursor: pointer; flex: 1;"><i class="fa-solid fa-camera"></i> 실시간 촬영</button>
            </div>
            <video id="cameraStream" style="display:none; width: 100%; height: 350px; border-radius: 12px; margin-bottom: 1rem; object-fit: cover; background: #000;" autoplay playsinline></video>
            <button type="button" id="captureBtn" onclick="takePhoto()" style="display:none; background: var(--primary); color: #000; padding: 15px 20px; border-radius: 8px; font-weight: bold; margin-bottom: 1rem; width: 100%; cursor: pointer; border: none; font-size: 1.1rem;"><i class="fa-solid fa-circle-dot"></i> 찰칵! 촬영하기</button>
            <canvas id="cameraCanvas" style="display:none;"></canvas>
"""

js_to_inject = """
        let videoStream = null;

        async function startCamera() {
            document.getElementById('previewArea').style.display = 'none';
            document.getElementById('cameraStream').style.display = 'block';
            document.getElementById('captureBtn').style.display = 'block';
            
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
                videoStream = stream;
                document.getElementById('cameraStream').srcObject = stream;
            } catch (err) {
                alert("카메라 접근 권한이 없거나 지원하지 않는 브라우저입니다. 파일 업로드를 이용해주세요.");
                stopCamera();
                document.getElementById('previewArea').style.display = 'flex';
            }
        }

        function takePhoto() {
            const video = document.getElementById('cameraStream');
            const canvas = document.getElementById('cameraCanvas');
            canvas.width = video.videoWidth || 640;
            canvas.height = video.videoHeight || 480;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            
            currentBase64 = canvas.toDataURL('image/jpeg', 0.8).split(',')[1];
            document.getElementById('imagePreview').src = canvas.toDataURL('image/jpeg', 0.8);
            
            stopCamera();
            
            document.getElementById('previewArea').style.display = 'flex';
            document.getElementById('imagePreview').style.display = 'block';
            document.getElementById('previewText').style.display = 'none';
            document.getElementById('analyzeBtn').disabled = false;
        }

        function stopCamera() {
            if (videoStream) {
                videoStream.getTracks().forEach(track => track.stop());
                videoStream = null;
            }
            document.getElementById('cameraStream').style.display = 'none';
            document.getElementById('captureBtn').style.display = 'none';
        }
"""

for filepath in files:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        if 'id="cameraStream"' not in content:
            # Inject HTML
            content = content.replace('<div class="preview-area"', html_to_inject + '\n            <div class="preview-area"')
            
            # Inject JS
            content = content.replace('let currentBase64', js_to_inject + '\n        let currentBase64')

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Updated {filepath}")
        else:
            print(f"Already updated {filepath}")
    except Exception as e:
        print(f"Failed {filepath}: {e}")
