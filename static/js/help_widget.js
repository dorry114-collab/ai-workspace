(function() {
    // 1. Help guides dictionary (by path)
    const guides = {
        "/": {
            title: "🌟 AI Workspace 사용법",
            desc: "AI Workspace는 일상생활, 투자, 메신저 소통, 운세, 건강 관리 등을 돕는 20가지 이상의 인공지능 툴을 한 곳에 모아둔 스마트 워크스페이스입니다.",
            steps: [
                "상단 카테고리 탭(로컬, 정보·분석, 소통 등)을 클릭하거나 검색창에서 키워드를 입력해 원하는 앱을 빠르게 찾습니다.",
                "사용하고 싶은 앱 카드를 클릭해 입장합니다.",
                "모든 개별 앱의 우측 하단에는 이 물음표(❓) 도움말 버튼이 있으므로, 사용이 막힐 때는 언제든지 클릭하여 사용법과 꿀팁을 확인하세요!"
            ],
            tip: "각 앱은 모바일 화면에서도 최적화되어 있습니다. 스마트폰의 홈 화면에 바로가기 앱으로 설치하면 더 편리하게 쓰실 수 있습니다!"
        },
        "/local": {
            title: "🗺️ AI 동네 탐색기 사용법",
            desc: "내 위치나 특정 동네를 중심으로 맛집, 카페, 빵집, 병원 등을 AI가 스캔하여 추천해주는 지도 기반의 핫플레이스 탐색기입니다.",
            steps: [
                "맛집, 카페, 병원 등 상단 탭에서 탐색하고 싶은 카테고리를 선택합니다.",
                "지도 중심점을 이동하거나 직접 주소를 입력하여 원하는 동네를 지정합니다.",
                "'주변 탐색 시작'을 클릭하면 AI가 추천 명소 목록과 추천 이유를 정밀 브리핑해 줍니다."
            ],
            tip: "모바일에서 내 위치 권한을 승인하면 현재 서 계신 곳 주변의 실시간 숨은 맛집과 카페를 즉시 분석해 드립니다."
        },
        "/planner": {
            title: "📍 AI 종합 플래너 사용법",
            desc: "완벽한 하루를 만들기 위한 여행 일정 기획, 당일 코스 추천, 그리고 여러 사람의 중간 약속 지점을 찾아주는 스마트 플래너입니다.",
            steps: [
                "<b>여행 플래너</b>: 가고 싶은 도시와 기간(예: 2박 3일)을 입력해 정밀 시간표를 받습니다.",
                "<b>원데이 코스</b>: 테마(데이트, 맛집 투어, 힐링 등)를 지정해 당일치기 코스를 동선별로 짭니다.",
                "<b>약속 중간지점</b>: 친구들의 출발지를 모두 입력하면 지하철 역 기준 최적의 중간지점과 그 주변의 갈 만한 곳을 추천해 줍니다."
            ],
            tip: "원데이 코스나 여행 일정을 짜고 나면, 카카오톡 공유 버튼을 눌러 동행인에게 즉시 계획을 전달해 보세요!"
        },
        "/estate": {
            title: "🏢 AI 부동산 스캐너 사용법",
            desc: "임장을 가기 전, 특정 지역의 아파트 단지나 오피스텔 등 매물의 가치와 시세 트렌드를 AI가 스캐너처럼 정밀 분석해 드립니다.",
            steps: [
                "분석을 원하는 지역명 또는 아파트 단지명을 입력합니다.",
                "'AI 부동산 분석 시작'을 누르면 실거래가 트렌드와 입지(학군, 교통, 인프라) 평가 리포트를 출력합니다.",
                "과거 대비 거래대금 변화율이나 매수 적정 타이밍 등에 대한 AI 의견을 참고하세요."
            ],
            tip: "실제 거주하거나 투자하기 전에 실거래 평당가와 매물 증감 추이를 미리 비교해 보면 호구 방지에 큰 도움이 됩니다."
        },
        "/lotto_scanner": {
            title: "🎯 AI 로또 명당 스캐너 사용법",
            desc: "사용자의 현재 위치나 가고자 하는 지역 주변에서 역대 로또 1등/2등 당첨자가 많이 배출된 '로또 명당 판매점'을 찾아 지도에 보여줍니다.",
            steps: [
                "검색창에 동네 이름을 입력하거나 내 위치 조회를 클릭합니다.",
                "반경 내 1등 배출 횟수가 많은 로또 명당들이 점수로 정렬되어 지도에 핀으로 표시됩니다.",
                "해당 명당을 클릭하면 카카오 맵 길찾기 경로로 바로 연동됩니다."
            ],
            tip: "가장 높은 당첨 횟수를 자랑하는 상위 판매점을 필터링해서 동선을 계획해 보세요!"
        },
        "/invest": {
            title: "📈 AI 주식 분석기 사용법",
            desc: "시장 트렌드와 거래대금 상위 종목을 스캔하고, 개별 종목의 차트 데이터와 보조 지표를 토대로 기술적 분석 리포트를 제공합니다.",
            steps: [
                "<b>시장 트렌드</b>: 오늘 하루 시장에서 어떤 테마와 업종으로 돈이 몰리고 있는지 한눈에 스캔합니다.",
                "<b>개별 종목 분석</b>: 종목 코드나 사명을 입력하면 최근 주가 차트와 함께 골든크로스, 볼린저 밴드 등 기술적 지표에 대한 AI 판단 리포트를 제공합니다."
            ],
            tip: "주식 분석 리포트는 전날 거래 종량 기준이며 투자 보조용이므로, 매매 결정을 내릴 때 참고용 지표로 삼아보세요."
        },
        "/youtube_studio": {
            title: "🎥 AI 유튜브 스튜디오 사용법",
            desc: "유튜브 채널명을 분석하여 조회수 높은 인기 비디오 목록을 뽑아주고, 긴 영상의 타임라인 구간 요약 및 핵심 정보 브리핑을 제공합니다.",
            steps: [
                "<b>인기영상 추출</b>: 궁금한 유튜브 채널명(예: @핸들 또는 채널 주소)을 넣고 조회하면 조회수 순 정렬 결과를 보여줍니다.",
                "<b>AI 영상 요약기</b>: 유튜브 영상의 웹 주소(URL)를 복사해 붙여넣으면 대본을 추출(또는 AI 오디오 청취)하여 5문장 요약, 인물/용어 설명, 심플한 Mermaid 관계도를 한눈에 그려줍니다."
            ],
            tip: "자막이 없는 영상의 경우 AI가 오디오를 직접 들으며 텍스트를 구성하므로 약간의 인코딩 시간이 추가로 필요할 수 있습니다."
        },
        "/shopping": {
            title: "🛒 AI 쇼핑 호구 방지기 사용법",
            desc: "온라인 쇼핑몰 링크나 상품 이름을 입력하면, 역대 최저가 비교와 후기 감성 분석을 통해 현재 가격이 적당한지, 혹은 '가짜 세일(호구 제품)'인지 AI가 감별해 줍니다.",
            steps: [
                "구매하려는 쇼핑몰 상품 페이지 주소 또는 상품명을 입력창에 붙여넣습니다.",
                "AI 가격 추이와 리뷰 평판을 종합 계산하여 '지금 사세요 / 기다리세요 / 사지 마세요' 3단계 경보를 발령합니다."
            ],
            tip: "광고성 리뷰나 중복 등록된 후기를 걸러내고 실제 사용자의 분노 섞인 솔직 후기 위주로 필터링하여 보고서를 작성해 줍니다."
        },
        "/message_hub": {
            title: "💬 AI 메시지 마스터 사용법",
            desc: "카톡 캡처 이미지나 텍스트 대화를 분석해 상대방이 기분 좋게 느낄 추천 답장을 제안하고, 작성하려는 글을 세련되게 변환하거나 직장인용 이메일 등으로 다듬어 줍니다.",
            steps: [
                "<b>카톡 답장 추천</b>: 대화 캡처본(이미지)이나 대화 텍스트를 입력하고 원하는 톤(친근하게, 시크하게 등)을 선택해 답장을 추천받습니다. '복사 및 이어가기'를 통해 연속 대화가 가능합니다.",
                "<b>메시지 작성 / 텍스트 다듬기</b>: 거친 텍스트나 사적인 내용을 정중한 격식체, 비즈니스 이메일, 혹은 부드러운 말투로 깔끔하게 탈바꿈합니다."
            ],
            tip: "자주 쓰는 카톡 말투 프로필을 분석 저장해두면, 나중에 내 카톡 말투를 그대로 흉내 내어 자연스러운 추천 답장을 생성해 줍니다."
        },
        "/love": {
            title: "💌 AI 카톡 썸 판독기 사용법",
            desc: "썸타는 상대방과의 카카오톡 대화록을 분석하여 나에 대한 호감도, 밀당 점수, 어조 속에 숨겨진 속마음을 연애 심리학 관점으로 해석해 줍니다.",
            steps: [
                "카카오톡 대화방 설정에서 '대화 내용 내보내기'로 추출한 텍스트 파일(.txt)을 준비합니다.",
                "텍스트 파일을 업로드하고 본인의 닉네임을 적어줍니다.",
                "분석을 누르면 감정 판독 리포트와 상대방의 나에 대한 관심도 변화 그래프가 완성됩니다."
            ],
            tip: "상대방이 바쁜 와중에도 답장을 빨리 보낸 구간이나 이모티콘 사용 횟수 등을 분석하여 과학적인 감정 지수를 도출합니다."
        },
        "/relation": {
            title: "💖 AI 카톡 관계 분석기 사용법",
            desc: "썸/연인, 부부, 친구, 비즈니스 등 다양한 관계에 맞춘 메신저 소통 비서입니다. 대화 전송량, 평균 답장 시간, 선톡 주도율 등 정밀 통계와 함께 Best/Worst 실제 대화 코칭 및 대화 심폐소생 선톡 멘트를 제공합니다.",
            steps: [
                "카카오톡 대화방에서 '대화 내용 내보내기'를 통해 추출한 텍스트 파일(`.txt`)을 준비합니다.",
                "대화방 성격(썸/연인, 부부, 친구, 비즈니스)을 선택하고 본인 닉네임을 정확히 입력한 뒤 파일과 함께 업로드합니다.",
                "동적으로 그려지는 소통 다이어그램 차트와 실제 대화를 2~3줄씩 인용한 1:1 대화 코칭 리포트를 확인합니다."
            ],
            tip: "특히 '부부' 모드의 경우 가사 분담, 육아 및 정서적 상호 작용 등 결혼 생활 특유의 관계 조율을 위한 피드백을 제공합니다."
        },
        "/english": {
            title: "🎓 AI 영어 회화 튜터 사용법",
            desc: "마치 실제 원어민 튜터와 대화하듯이 롤플레잉 상황극을 벌이며 영어 스피킹과 텍스트 채팅을 연습하고, 매 문장마다 문법 및 어색한 표현에 대한 교정 피드백을 받습니다.",
            steps: [
                "대화하고 싶은 상황(공항, 카페, 비즈니스 미팅 등)과 난이도를 설정합니다.",
                "튜터의 영어 질문에 마이크 아이콘을 누르고 말하거나 직접 텍스트로 답장합니다.",
                "대답이 어색하거나 틀리면 AI가 즉시 친절한 한국어 설명과 함께 '더 자연스러운 3가지 표현' 추천 카드를 제시합니다."
            ],
            tip: "TTS 발음 듣기 버튼을 활용하여 원어민의 억양과 발음을 그대로 섀도잉하며 따라 말해 보세요."
        },
        "/mystic": {
            title: "🔮 AI 운세 종합관 사용법",
            desc: "동양 명리학 기반의 사주팔자 풀이, 타로 카드 셔플 및 리딩, 그리고 신비로운 꿈의 상징을 풀이해주는 종합 역술관입니다.",
            steps: [
                "<b>사주팔자</b>: 이름, 생년월일시(양력/음력)를 입력하여 타고난 오행 분포와 신년운세를 봅니다.",
                "<b>타로 카드</b>: 고민거리를 머릿속으로 떠올리며 타로 덱에서 신중하게 3장의 카드를 뽑아 과거/현재/미래의 운세를 리딩합니다.",
                "<b>꿈 해몽</b>: 지난밤 꿈속에 등장했던 강렬한 장면이나 사물을 적어 숨은 심리적 의미와 예지몽 여부를 해석받습니다."
            ],
            tip: "타로 카드는 셔플 순간의 진정성이 중요하므로, 한 가지 질문에 한 번만 덱을 섞는 것이 바람직합니다."
        },
        "/health": {
            title: "🥗 AI 건강 코치 사용법",
            desc: "철저한 칼로리 조율과 운동 계획을 짜주는 다이어트 비서와, 냉장고 속 남은 재료를 적기만 하면 근사한 요리 레시피를 제안해주는 냉장고 셰프가 하나로 합쳐진 건강 관리 앱입니다.",
            steps: [
                "<b>다이어트 코치</b>: 현재 키, 몸무게, 목표 체중과 하루 활동량을 입력하면 AI가 맞춤형 일일 식단 및 홈트레이닝 루틴을 처방합니다.",
                "<b>냉장고 파먹기</b>: 집에 있는 남은 식재료(예: 스팸, 김치, 두부)를 적으면 즉석에서 가능한 요리 방법과 레시피를 전수해 줍니다."
            ],
            tip: "다이어트 식단에서 피해야 할 알레르기 유발 식품이나 선호하지 않는 단백질 소스를 입력하여 배제할 수도 있습니다."
        },
        "/diary": {
            title: "📝 티키타카 AI 일기장 사용법",
            desc: "매번 혼자 길게 쓰기 어려운 일기를 AI가 다정한 친구처럼 질문을 건네고 맞장구치면서, 자연스럽게 한 편의 감동적인 일기로 완성해 주는 소통형 다이어리입니다.",
            steps: [
                "일기 작성을 시작하면 AI가 '오늘 하루 중 가장 기억에 남는 순간은 무엇이었나요?'처럼 질문을 건넵니다.",
                "편하게 한두 줄 대답을 적으면 AI가 리액션을 하며 다음 대화를 유도합니다.",
                "3~4번의 티키타카 대화가 끝나면 AI가 대화 내용을 한데 모아 감성적인 오늘 하루 일기로 멋지게 편집해 줍니다."
            ],
            tip: "길게 쓰지 않아도 되며, 친구와 카톡하듯이 편하게 대답하기만 하면 AI가 전체 글자 수와 문맥을 완성도 있게 정리해 줍니다."
        },
        "/therapist": {
            title: "🌱 AI 힐링 대나무숲 사용법",
            desc: "남들에게 말하지 못할 가슴속 고민, 스트레스, 외로움을 익명으로 털어놓고, 전문 심리상담사 못지않은 따뜻한 공감과 위로의 편지를 받아보는 힐링 공간입니다.",
            steps: [
                "마음속 깊은 곳에 있는 고민거리나 속상한 이야기를 입력창에 자유롭게 작성합니다.",
                "'털어놓기'를 누르면 AI가 진심 어린 위로의 리액션과 따스한 감정 처방 리포트를 작성해 드립니다."
            ],
            tip: "어떤 개인정보도 저장되지 않으므로, 익명이 보장된 상태에서 홀가분하게 감정을 털어놓으셔도 안전합니다."
        },
        "/vision_ai": {
            title: "👁️ AI 비주얼 분석 사용법",
            desc: "업로드한 인물 사진을 정밀 스캔하여 전통 동양 관상학을 기준으로 눈/코/입 가치와 운세를 해석해주거나, 오늘의 OOTD 스타일링 패션 센스를 냉정하게 평가해 줍니다.",
            steps: [
                "<b>관상 분석</b>: 얼굴이 잘 보이는 인물 사진을 업로드하고 분석을 시작하여 연애운, 재물운, 직업운 리포트를 받습니다.",
                "<b>패션 평가</b>: 오늘의 전신 착장 사진을 올리면 패션 센스 점수와 보완할 색상/액세서리 팁을 제시합니다."
            ],
            tip: "관상 분석 시 안경이나 마스크를 벗고, 정면에서 얼굴 윤곽과 이목구비가 가려지지 않게 찍은 밝은 사진을 업로드해야 정확도가 높아집니다."
        },
        "/shorts": {
            title: "🎬 Shorts 제작기 사용법",
            desc: "제작하고 싶은 영상의 스크립트나 주제를 입력하면, AI가 목소리 음성(TTS)을 합성하고 그에 어울리는 배경 자막 카드를 결합하여 쇼츠 영상 파일(`.mp4`)을 즉석에서 조립해 줍니다.",
            steps: [
                "쇼츠 영상의 핵심 주제나 스크립트 대본 텍스트를 입력창에 작성합니다.",
                "내레이션을 진행할 목소리 성우(남성/여성/속도)와 배경 카드 스타일을 선택합니다.",
                "'쇼츠 영상 생성'을 클릭하면 인코딩을 거쳐 즉시 시청 및 다운로드 가능한 세로형 쇼츠 동영상이 랜더링됩니다."
            ],
            tip: "텍스트에 단락 구분을 많이 지어주면 자막 카드가 적절한 타이밍에 끊겨 자연스러운 가독성을 제공합니다."
        },
        "/prompt": {
            title: "🎨 프롬프트 발전기 사용법",
            desc: "인공지능에게 질문할 때 원하는 고품질 답변을 얻을 수 있도록, 초기 아이디어를 기반으로 5단계 질의응답을 거쳐 마스터 프롬프트로 고도화해 주는 도구입니다.",
            steps: [
                "대략적으로 만들고 싶은 프롬프트 아이디어(예: '영어 메일 작성해주는 프롬프트')를 적습니다.",
                "AI가 더 명확한 기준을 잡기 위해 핵심 질문을 하나씩 던집니다.",
                "5번의 질문에 대답하고 나면, ChatGPT나 Claude 등에 그대로 복사해서 쓸 수 있는 완벽한 가이드라인이 명시된 마스터 프롬프트가 완성됩니다."
            ],
            tip: "질문에 답변할 때 예시를 그대로 변형해서 적어주거나 원하는 명확한 조건을 추가할수록 결과물의 밀도가 높아집니다."
        },
        "/lotto": {
            title: "🎯 로또 번호 추천 사용법",
            desc: "역대 로또 당첨 데이터의 통계를 기반으로 자주 나온 번호(HOT)와 적게 나온 번호(COLD)를 분석하여 당첨 확률을 높일 수 있는 필터링 조합을 시뮬레이션하고 번호를 추천해 줍니다.",
            steps: [
                "추천받고 싶은 필터 조합(자주 나온 번호 개수, 적게 나온 번호 개수 지정)을 설정합니다.",
                "'번호 생성하기'를 클릭하면 1등 최다 번호 통계 풀에서 정밀 배합된 5게임 조합 리스트를 보여줍니다."
            ],
            tip: "역대 누적 통계상 가장 출현 빈도가 높은 10개 번호와 가장 출현 빈도가 적은 10개 번호를 섞어서 조합하는 전략이 가능합니다."
        }
    };

    // Get current path (strip query params and normalize trailing slashes)
    let currentPath = window.location.pathname.replace(/\/$/, "");
    if (currentPath === "") currentPath = "/";

    // Only proceed if we have a guide for this path
    const guide = guides[currentPath];
    if (!guide) return;

    // 2. Inject CSS Styles
    const css = `
        .floating-help-btn {
            position: fixed;
            bottom: 24px;
            right: 24px;
            width: 48px;
            height: 48px;
            border-radius: 50%;
            background: linear-gradient(135deg, #6366f1, #a855f7);
            border: 1px solid rgba(255, 255, 255, 0.2);
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
            box-shadow: 0 8px 30px rgba(168, 85, 247, 0.4);
            cursor: pointer;
            z-index: 999990;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .floating-help-btn:hover {
            transform: scale(1.1) rotate(5deg);
            box-shadow: 0 12px 35px rgba(168, 85, 247, 0.6);
        }
        @media (max-width: 768px) {
            .floating-help-btn {
                bottom: 80px; /* Avoid overlapping mobile action buttons */
                right: 16px;
                width: 44px;
                height: 44px;
                font-size: 1.15rem;
            }
        }
        .help-modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(11, 14, 20, 0.6);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 999995;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }
        .help-modal-overlay.active {
            opacity: 1;
            pointer-events: auto;
        }
        .help-modal-card {
            background: rgba(22, 27, 34, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 20px;
            width: 90%;
            max-width: 480px;
            max-height: 80vh;
            overflow-y: auto;
            padding: 24px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
            color: #f0f6fc;
            transform: scale(0.9) translateY(20px);
            transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
            position: relative;
        }
        .help-modal-overlay.active .help-modal-card {
            transform: scale(1) translateY(0);
        }
        .help-modal-close {
            position: absolute;
            top: 18px;
            right: 18px;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.05);
            border: none;
            color: #8b949e;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.95rem;
            transition: all 0.2s;
        }
        .help-modal-close:hover {
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
        }
        .help-modal-title {
            font-size: 1.22rem;
            font-weight: 800;
            margin-bottom: 8px;
            background: linear-gradient(135deg, #ffffff, #c4b5fd);
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .help-modal-desc {
            font-size: 0.86rem;
            color: #8b949e;
            line-height: 1.5;
            margin-bottom: 20px;
            word-break: keep-all;
        }
        .help-step-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .help-step-item {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            padding: 12px 14px;
            font-size: 0.88rem;
            line-height: 1.45;
            color: #e6edf3;
        }
        .help-step-num {
            background: rgba(168, 85, 247, 0.15);
            color: #d8b4fe;
            font-weight: 700;
            font-size: 0.72rem;
            padding: 2px 8px;
            border-radius: 20px;
            display: inline-block;
            margin-bottom: 4px;
        }
        .help-tip-box {
            margin-top: 18px;
            background: rgba(251, 191, 36, 0.06);
            border-left: 3px solid #fbbf24;
            border-radius: 8px;
            padding: 12px 14px;
            font-size: 0.82rem;
            line-height: 1.45;
            color: #fef08a;
            display: flex;
            gap: 8px;
            align-items: flex-start;
        }
        .help-tip-box i {
            color: #fbbf24;
            margin-top: 2px;
            font-size: 0.95rem;
        }
        .help-tip-text {
            flex: 1;
        }
    `;

    const styleEl = document.createElement("style");
    styleEl.textContent = css;
    document.head.appendChild(styleEl);

    // 3. Inject Button and Modal HTML
    const button = document.createElement("div");
    button.className = "floating-help-btn";
    button.innerHTML = '<i class="fa-regular fa-circle-question"></i>';
    button.title = "사용 가이드 보기";
    document.body.appendChild(button);

    const overlay = document.createElement("div");
    overlay.className = "help-modal-overlay";
    
    // Build steps HTML
    let stepsHtml = "";
    guide.steps.forEach((step, idx) => {
        stepsHtml += `
            <div class="help-step-item">
                <span class="help-step-num">${idx + 1}단계</span>
                <div>${step}</div>
            </div>
        `;
    });

    overlay.innerHTML = `
        <div class="help-modal-card">
            <button class="help-modal-close"><i class="fa-solid fa-xmark"></i></button>
            <div class="help-modal-title">${guide.title}</div>
            <div class="help-modal-desc">${guide.desc}</div>
            <div class="help-step-list">
                ${stepsHtml}
            </div>
            <div class="help-tip-box">
                <i class="fa-regular fa-lightbulb"></i>
                <div class="help-tip-text">${guide.tip}</div>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    // 4. Click Event Listeners
    button.addEventListener("click", function(e) {
        e.stopPropagation();
        overlay.classList.add("active");
    });

    const closeBtn = overlay.querySelector(".help-modal-close");
    closeBtn.addEventListener("click", function() {
        overlay.classList.remove("active");
    });

    overlay.addEventListener("click", function(e) {
        if (e.target === overlay) {
            overlay.classList.remove("active");
        }
    });

    document.addEventListener("keydown", function(e) {
        if (e.key === "Escape" && overlay.classList.contains("active")) {
            overlay.classList.remove("active");
        }
    });
})();
