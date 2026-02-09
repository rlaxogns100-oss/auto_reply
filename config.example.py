# ==========================================
# [사용자 설정 예시 파일]
# ==========================================
# 이 파일을 'config.py'로 복사한 후 실제 값을 입력하세요.
# 
# Windows: copy config.example.py config.py
# Mac/Linux: cp config.example.py config.py

# 1. 네이버 계정 정보
NAVER_ID = "horse324"
NAVER_PW = "1qaz2wsx"

# 2. Gemini API 키 (Google AI Studio에서 발급받으세요)
# 발급 방법: https://aistudio.google.com/apikey
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"

# 3. Azure OpenAI 설정 (선택사항 - Gemini 대신 사용 가능)
# Azure Portal에서 발급받으세요
AZURE_OPENAI_ENDPOINT = "https://your-resource.cognitiveservices.azure.com/openai/responses"
AZURE_OPENAI_API_KEY = "YOUR_AZURE_OPENAI_API_KEY_HERE"
AZURE_OPENAI_API_VERSION = "2025-04-01-preview"
AZURE_OPENAI_DEPLOYMENT = "gpt-5.2-chat-4"  # 배포 이름

# 4. AI 모델 선택 ("gemini" 또는 "azure")
# - gemini: Google Gemini API 사용
# - azure: Azure OpenAI API 사용
AI_MODEL_PROVIDER = "gemini"

# 5. 타겟 카페 Club ID (수만휘 ID)
CLUB_ID = "10197921"

# 5-1. 검색할 게시판(메뉴) ID 목록. 비우거나 없으면 전체(0) 검색
# 수만휘: 4427=Team08 수험생 게시판, 201=Team09 수험생 게시판
CAFE_MENU_IDS = [4427, 201]

# 6. UniRoad Backend API URL (RAG 기능 사용 시 필요)
# 로컬 개발: http://localhost:8000
# 프로덕션: http://3.107.178.26 (또는 실제 서버 주소)
BACKEND_URL = "http://localhost:8000"
