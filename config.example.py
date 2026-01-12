# ==========================================
# [사용자 설정 예시 파일]
# ==========================================
# 이 파일을 'config.py'로 복사한 후 실제 값을 입력하세요.
# 
# Windows: copy config.example.py config.py
# Mac/Linux: cp config.example.py config.py

# 1. 네이버 계정 정보
NAVER_ID = "your_naver_id"
NAVER_PW = "your_naver_password"

# 2. Gemini API 키 (Google AI Studio에서 발급받으세요)
# 발급 방법: https://aistudio.google.com/apikey
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"

# 3. 타겟 카페 Club ID (수만휘 ID)
CLUB_ID = "10197921"

# 4. 감지할 키워드 (제목에 이 단어가 있으면 댓글 달림)
SEARCH_KEYWORDS = ['생기부', '세특']

# 5. 댓글 멘트 리스트 (랜덤으로 하나 선택됨)
REPLY_MESSAGES = [
    "서울대 기계공학부 재학 중인데 고민되는 생기부 있으시면 보고 피드백 드릴게요.",
    "서울대 학생인데 생기부 킬/패스 판독해 드릴 수 있습니다.",
    "지망 학과가 저랑 비슷하네요. 쪽지 주시면 합격한 세특 예시 알려드릴게요."
]
