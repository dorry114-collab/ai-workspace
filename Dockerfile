# 파이썬 3.12 슬림 버전 (가볍고 빠른 이미지 기반)
FROM python:3.12-slim

# 영상/음성 편집에 꼭 필요한 ffmpeg를 시스템에 먼저 설치합니다.
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 서버 내부의 작업 폴더를 /app으로 설정합니다.
WORKDIR /app

# 파이썬 라이브러리 목록 파일만 '먼저' 복사합니다. (도커의 핵심 캐시 마법!)
COPY requirements.txt .

# 라이브러리들을 설치합니다. (이 과정이 3~4분 걸리지만, requirements.txt를 안 건드리면 다음부턴 '0초' 만에 넘어갑니다)
RUN pip install --no-cache-dir -r requirements.txt

# 이제 나머지 내가 짠 모든 소스 코드(html, py 파일 등)를 복사합니다.
COPY . .

# Render 서버에서 쏘아주는 포트(PORT)로 gunicorn 웹 서버를 실행합니다.
# 워커가 죽지 않게 넉넉한 타임아웃(300초=5분)을 줍니다.
CMD gunicorn main:app -b 0.0.0.0:$PORT --timeout 300
