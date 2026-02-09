# 수만휘 카페 설정
import os
from dotenv import load_dotenv

# 상위 디렉토리의 .env 로드
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

NAVER_ID = "horse324"
NAVER_PW = "1qaz2wsx"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CLUB_ID = "10197921"
BACKEND_URL = "http://localhost:8000"

CAFE_NAME = "suhui"
CAFE_URL = "https://cafe.naver.com/suhui"

# 검색할 게시판 ID (수만휘 전체글보기)
CAFE_MENU_IDS = [4427, 201]

# 봇 닉네임 목록 (댓글 중복 체크용) - 여러 계정 사용 시 모두 등록
MY_NICKNAMES = ["하늘담아", "도군", "화궁"]
