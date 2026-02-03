import time
import random
import platform
import urllib.parse 
import os 
import json
import requests
import signal
import sys
import pickle
from datetime import datetime
import google.generativeai as genai
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import UnexpectedAlertPresentException, NoAlertPresentException
import config

# ==========================================
# [서버용 설정]
# ==========================================
# 스크립트 디렉토리 기준으로 경로 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_FILE = os.path.join(SCRIPT_DIR, "naver_cookies.pkl")
BOT_CONFIG_FILE = os.path.join(SCRIPT_DIR, "bot_config.json")
COMMENT_HISTORY_FILE = os.path.join(SCRIPT_DIR, "comment_history.json")
STOP_FLAG_FILE = os.path.join(SCRIPT_DIR, ".stop_bot")

# Headless 모드 (서버용)
HEADLESS_MODE = os.environ.get("HEADLESS", "true").lower() == "true"

# 봇 종료 플래그
should_stop = False

def signal_handler(signum, frame):
    """SIGTERM/SIGINT 시그널 처리"""
    global should_stop
    print("\n[봇] 종료 신호 수신, 안전하게 종료 중...")
    should_stop = True

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def check_stop_flag():
    """정지 플래그 파일 확인"""
    if os.path.exists(STOP_FLAG_FILE):
        os.remove(STOP_FLAG_FILE)
        return True
    return False

def load_bot_config():
    """봇 설정 파일 로드"""
    default_config = {
        "min_delay_seconds": 50,
        "comments_per_hour_min": 5,
        "comments_per_hour_max": 10,
        "rest_minutes": 3
    }
    if os.path.exists(BOT_CONFIG_FILE):
        try:
            with open(BOT_CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                default_config.update(loaded)
        except:
            pass
    return default_config

def save_comment_history(post_url, post_title, comment_content, success=True):
    """댓글 기록 저장"""
    history = []
    if os.path.exists(COMMENT_HISTORY_FILE):
        try:
            with open(COMMENT_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            history = []
    
    record = {
        "timestamp": datetime.now().isoformat(),
        "post_url": post_url,
        "post_title": post_title,
        "comment": comment_content,
        "success": success
    }
    history.append(record)
    
    # 최근 500개만 유지
    if len(history) > 500:
        history = history[-500:]
    
    with open(COMMENT_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def load_cookies(driver):
    """쿠키 파일로 로그인"""
    if not os.path.exists(COOKIE_FILE):
        print(f"[에러] 쿠키 파일 없음: {COOKIE_FILE}")
        print("[안내] 로컬에서 get_cookies.py를 실행하여 쿠키를 생성하세요.")
        return False
    
    try:
        driver.get("https://naver.com")
        time.sleep(2)
        
        with open(COOKIE_FILE, "rb") as f:
            cookies = pickle.load(f)
        
        for cookie in cookies:
            # 일부 쿠키 속성 제거 (호환성)
            if 'expiry' in cookie:
                del cookie['expiry']
            try:
                driver.add_cookie(cookie)
            except:
                pass
        
        driver.refresh()
        time.sleep(2)
        
        # 로그인 확인
        page_source = driver.page_source
        if "로그아웃" in page_source or "내정보" in page_source or "MY" in page_source:
            print("[봇] 쿠키 로그인 성공!")
            return True
        else:
            print("[에러] 쿠키 만료됨. 다시 추출하세요.")
            return False
            
    except Exception as e:
        print(f"[에러] 쿠키 로드 실패: {e}")
        return False

# ==========================================
# [설정] AI 모델 및 API 키
# ==========================================
HISTORY_FILE = os.path.join(SCRIPT_DIR, "visited_history.txt")

# config.py에서 API 키 가져오기
genai.configure(api_key=config.GEMINI_API_KEY)

# Query Agent (RAG 검색 쿼리 생성용) - gemini-2.5-flash-lite
try:
    query_agent = genai.GenerativeModel('gemini-2.5-flash-lite')
    print("[INFO] Query Agent: gemini-2.5-flash-lite")
except:
    query_agent = genai.GenerativeModel('gemini-2.0-flash')
    print("[INFO] Query Agent: gemini-2.0-flash (fallback)")

# Answer Agent (답변 생성용) - gemini-3-flash-preview
try:
    answer_agent = genai.GenerativeModel('gemini-3-flash-preview')
    print("[INFO] Answer Agent: gemini-3-flash-preview")
except:
    answer_agent = genai.GenerativeModel('gemini-2.5-flash')
    print("[INFO] Answer Agent: gemini-2.5-flash (fallback)")

TARGET_KEYWORDS = [
    # 1. [핵심] 정시 파이터들의 공통 언어 (가장 중요)
    "정시", "표점", "표준점수", "환산점수", "백분위",
    "추합", "예비", "최초합", "전찬", "추가합격",
    "상향", "소신", "안정", "하향", "스나", "빵꾸", # '스나', '빵꾸'는 기회를 노리는 은어

    # 2. [확장] 대학 라인 (중위권~인서울 전체로 확장)
    "인서울", "수도권", "지거국", "대학 라인", "어디가",
    "건동홍", "국숭세단", "광명상가", "인가경", "한서삼", # 학생들이 가장 많이 고민하는 라인

    # 3. [대학명]
    "서울대", "연세대", "고려대", "성균관대", "한양대",
    "중앙대", "건국대", "한국외대", "중대", "경희대",
    "동국대", "명지대", "서강대", "광운대", "선리대",
    "숭실대", "이화여대"      
]
# Backend API URL (config에서 가져오기, 기본값: 로컬)
BACKEND_URL = getattr(config, 'BACKEND_URL', 'http://localhost:8000')

# ==========================================
# [Query Agent] 게시글 분석 및 RAG 검색 쿼리 생성 (gemini-2.5-flash-lite)
# ==========================================
QUERY_AGENT_PROMPT = """당신은 대학 입시 커뮤니티 게시글을 분석하는 **Query Agent**입니다.

## 역할
게시글을 읽고 **도움이 필요한 수험생의 질문**인지 판단한 후, 필요시 RAG 검색을 위한 함수 호출을 생성하세요.

## 🚨 1차 필터 - PASS 해야 하는 경우 (빈 배열 반환)
다음 중 하나라도 해당되면 function_calls를 빈 배열로 반환하세요:
1. **이미 합격한 사람**: "합격 후기", "최초합", "합격했습니다", "대학 갑니다" 등
2. **정보 공유/자료 배포**: 질문이 아니라 팁을 알려주는 글, 자료 나눔글
3. **광고/홍보**: 학원 홍보, 과외 모집, 스터디 모집
4. **공지사항**: 카페 공지, 필독 등
5. **단순 잡담**: 연애, 유머, 입시와 무관한 일상
6. 공부법, 학교생활에 관한 질문
7. 이외 기타 '입시요강, 입결, 대학별 점수 환산&비교' 자료를 통해 대답할 수 없는 질문.(예, 학원 추천, 커리 추천, 공부법 상담, 멘탈 상담 등)
8. 시간상 유효하지 않은 질문(예를 들어, 2026 입시 합격 가능성에 대한 질문은 이미 결과가 나왔으므로 유효하지 않음.)

## '입시요강, 입결, 대학별 점수 환산&비교' 자료를 통해 명확하게 대답 가능한 질문만 까다롭게 선정하세요. 그 외 질문은 모두 빈 배열로 반환하세요.



## 정체성
당신의 역할은 정보 검색을 위한 json 형식의 함수 호출입니다. 당신이 찾은 정보와 대화의 맥락을 종합하여 main agent가 최종적인 답변을 생성합니다, 정확한 함수를 올바르게 호출하여 정보를 검색하세요.
단일 질문 뿐 아니라 이전 대화 히스토리 내용을 고려하여 적절하게 판단하세요.
이전 히스토리의 출력은 main_agent의 출력 형식입니다. 따라하지 말고 아래에 명시된 출력 형식을 지키세요.

## 시점 동기화
- 2026년 1월 (2026학년도 입시 종료)
- "올해" = 2026학년도
- "작년 입결" = 2025학년도
- "나 고1인데" -> 2028년도 입시, "나 18살인데" -> 2027년도 입시(나이에 맞는 입시 요강 우선 탐색)
- 입시 결과는 최신 자료만 사용(2025학년도)

## 사용 가능한 함수

### univ(university, query)
특정 대학의 입시 정보를 검색합니다.
- university: 대학 정식명칭 (서울대학교, 경희대학교)
- query: 검색 쿼리 (연도 + 전형 + 학과 명시)

예시:
- "서울대 가는 법" -> univ("서울대학교", "서울대학교 2026학년도 모집요강")
- "서울대 기계과 정시" → univ("서울대학교", "2026학년도 기계공학부 정시")
- "나 고1인데 경희대 농어촌 전형 알려줘" → univ("경희대학교", "2028 경희대학교 농어촌 전형")

### consult(scores, target_univ, target_major, target_range)
대학 입결 조회, 학생 성적 대학별 환산점수 변환, 합격 가능성 평가
학생 성적을 분석하여 합격 가능성을 평가합니다. 환산점수 계산 포함.
#### 주의: 성적 정보가 질문에 있으면 scores 로 사용, 질문에 없고 history에 있으면 그 정보를 scores 로 사용, 둘 다 없으면 consult 호출 안 함
- scores: 성적 딕셔너리 {"국어": {"type": "등급", "value": 1}, ...}
- target_univ: 분석 대상 대학 리스트 (없으면 [])
- target_major: 관심 학과 리스트 (없으면 [])
- target_range: 분석 범위 리스트 (없으면 [] = 전체 범위)

#### 성적 입력 형식
1. 축약형 (5자리): "11232" → 국어/수학/영어/탐구1/탐구2 등급
2. 축약형 (6자리): "211332" → 한국사/국어/수학/영어/탐구1/탐구2 등급
3. 등급: "국어 1등급", "수학 2등급"
4. 표준점수: "수학 140점", "수학 표준점수 140"
5. 백분위: "국어 백분위 98"

#### 과목명 처리
- 일반 과목명 (선택과목 미언급): 국어, 수학, 영어, 한국사, 탐구1, 탐구2 → 그대로 출력
- 구체적 선택과목 (명시된 경우): 화법과작문(화작), 언어와매체(언매), 미적분, 확률과통계(확통), 기하, 생명과학1(생1), 지구과학1(지1), 생활과윤리(생윤), 사회문화(사문) 등 → 과목명 그대로 출력
- 성적이 추정 가능한 경우에는 임의로 추정하여 출력: "국어 영어는 1인데 수학은 좀 못해요 -> 3등급으로 추정"

#### 성적 출력 형식
```json
{
  "scores": {
    "국어": {"type": "등급", "value": 1},
    "수학": {"type": "표준점수", "value": 140},
    "영어": {"type": "등급", "value": 2},
    "한국사": {"type": "등급", "value": 1},
    "탐구1": {"type": "등급", "value": 1, "과목명": "생활과윤리"},
    "탐구2": {"type": "등급", "value": 2, "과목명": "사회문화"}
  }
}
```
- type: "등급", "표준점수", "백분위"
- 탐구 과목은 키를 "탐구1", "탐구2"로 고정하고, 과목명이 언급된 경우 "과목명" 필드 추가
- 한국사는 항상 포함 (미언급 시 1등급으로 기본 추정)

성적 예시:
- "11232" → {"국어": {"type": "등급", "value": 1}, "수학": {"type": "등급", "value": 1}, "영어": {"type": "등급", "value": 2}, "한국사": {"type": "등급", "value": 1}, "탐구1": {"type": "등급", "value": 3}, "탐구2": {"type": "등급", "value": 2}}
- "국어 화작 1등급, 수학 미적 140점" → {"국어": {"type": "등급", "value": 1, "선택과목": "화법과작문"}, "수학": {"type": "표준점수", "value": 140, "선택과목": "미적분"}}
- "생윤 2등급 사문 1등급" → {"탐구1": {"type": "등급", "value": 2, "과목명": "생활과윤리"}, "탐구2": {"type": "등급", "value": 1, "과목명": "사회문화"}}
- "물1 지1 1등급" → {"탐구1": {"type": "등급", "value": 1, "과목명": "물리학1"}, "탐구2": {"type": "등급", "value": 1, "과목명": "지구과학1"}}

target_range 옵션 (새로운 판정 기준):
- ["안정"]: 내 점수 >= 안정컷 (safeScore), 합격 확률 매우 높음
- ["적정"]: 내 점수 >= 적정컷 (appropriateScore), 합격 가능성 높음
- ["소신"]: 내 점수 >= 소신컷 (expectedScore), 합격 가능성 있음
- ["도전"]: 내 점수 >= 도전컷 (challengeScore), 도전적인 지원
- ["어려움"]: 내 점수 < 도전컷, 합격 어려움
- []: 빈 배열 = 모든 범위 (기본값), score가 주어지지 않으면 항상 빈 배열
- 학생이 자기 성적만 입력한 경우 -> [안정, 적정, 소신]
예시:
- "나 11232인데 경희대 갈 수 있어?" → consult(scores, ["경희대학교"], [], [])
- "11112로 기계공학 어디 갈까?" → consult(scores, [], ["기계공학"], [안정, 적정, 소신])
- '내 성적 언매 99, 미적 100, 영어 1등급, 물1 85, 화2 93이야: -> consult(scores, [], [], [안정, 적정, 소신])
- "적정 대학 추천해줘" → consult(scores, [], [], ["적정"])
- "도전으로 서울대 연세대 가능해?" → consult(scores, ["서울대학교", "연세대학교"], [], ["도전"])

## 출력 형식
반드시 JSON만 출력하세요. 다른 텍스트 절대 금지.

### 단일 함수 호출 예시 (올해 수능으로 서울대 가려면 어떻게 해?)
```json
{
  "function_calls": [
    {
      "function": "univ",
      "params": {
        "university": "서울대학교",
        "query": "2026학년도 서울대학교 정시 모집요강", "2025학년도 서울대학교 정시 입결"
      }
    }
  ]
}
```

### 성적 분석 예시 (나 11232인데 경희대 갈 수 있어?)
```json
{
  "function_calls": [
    {
      "function": "consult",
      "params": {
        "scores": {
          "국어": {"type": "등급", "value": 1},
          "수학": {"type": "등급", "value": 1},
          "영어": {"type": "등급", "value": 2},
          "탐구1": {"type": "등급", "value": 3},
          "탐구2": {"type": "등급", "value": 2}
        },
        "target_univ": ["경희대학교"],
        "target_major": [],
        "target_range": []
      }
    },
    {
      "function": "univ",
      "params": {
        "university": "경희대학교",
        "query": "2026학년도 경희대학교 정시 모집요강"
      }
    }
  ]
}
```

### 적정 대학 추천 예시 (11112인데 적정 대학 추천해줘)
```json
{
  "function_calls": [
    {
      "function": "consult",
      "params": {
        "scores": {
          "국어": {"type": "등급", "value": 1},
          "수학": {"type": "등급", "value": 1},
          "영어": {"type": "등급", "value": 1},
          "탐구1": {"type": "등급", "value": 1},
          "탐구2": {"type": "등급", "value": 2}
        },
        "target_univ": [],
        "target_major": [],
        "target_range": ["적정"]
      }
    }
  ]
}
```

## 판단 규칙
1. **대학명 정규화**: 서울대 → 서울대학교, 고대 → 고려대학교
2. **연도 명시**: 항상 "XXXX학년도" 포함
3. **성적 질문**: 성적 + 특정 대학 언급 시 consult + univ 동시 호출
4. **대학명 언급 없는 막연한 질문에는 consult 호출**:  
    - "내 성적(언급)으로 어디 갈 수 있어?" → consult(scores, [], [], [안정, 적정, 소신])
    - "메디컬 가려면 공부 얼마나 해야 해?" → consult(scores, [], ['의예과', '치예과', '한의예과', '수의예과', '약학과'], [])
5. **비교 질문**: 여러 대학 비교 시 각각 univ 호출
6. **기본값은 빈 배열**: target_univ, target_major, target_range 모두 명시 안되면 []
7. **정확한 의도 파악**: 
    - "그래도 어디까진 확실히 될까?" -> consult(scores, [], [], ["적정", "안정"]), 
    - "어디까지 갈 수 있을까?" -> consult(scores, [], [], ["도전", "소신"])
8. 애매하면 포괄적으로 정보 가져오기(어짜피 main agent에서 정보 선별, 단 최대 호출 수 3개로 제한)
    - "수도권 공대 중에 2등급이 갈 곳 알려줘" -> consult(scores, [], [공학], ["적정", "안정"]) (수도권은 변수 설정이 안 되지만, 모든 공대에 대해서 조사하면 main agent가 선별), 
    - "SKY 중에 공대 1000명 넘게 뽑는 곳 알려줘 -> 서울대, 연세대, 고려대 전부 호출

"""

def generate_function_calls(title, content):
    """
    Query Agent로 게시글 분석 및 함수 호출 생성
    
    Returns:
        list: function_calls 배열 (PASS인 경우 빈 배열)
        None: 에러 발생 시
    """
    try:
        prompt = f"""{QUERY_AGENT_PROMPT}

[게시글]
제목: {title}
본문: {content[:1000]}

위 게시글을 분석하여 function_calls를 JSON 형식으로 생성하세요.
"""
        
        generation_config = {
            "temperature": 0.0,
            "max_output_tokens": 2048,
            "response_mime_type": "application/json"
        }
        
        response = query_agent.generate_content(prompt, generation_config=generation_config)
        result_text = response.text.strip()
        
        # JSON 파싱
        result = json.loads(result_text)
        function_calls = result.get("function_calls", [])
        
        if not function_calls:
            print(f"  -> [Query Agent] PASS (도움 불필요)")
            return []
        
        print(f"  -> [Query Agent] {len(function_calls)}개 함수 호출 생성")
        for call in function_calls:
            print(f"     - {call.get('function')}: {call.get('params', {}).get('university', '')} {call.get('params', {}).get('query', '')[:50]}")
        
        return function_calls
        
    except json.JSONDecodeError as e:
        print(f"  -> [Query Agent] JSON 파싱 실패: {e}")
        print(f"     원본: {result_text[:200]}")
        return None
    except Exception as e:
        print(f"  -> [Query Agent] 에러: {e}")
        return None


# ==========================================
# [RAG] Backend API 호출로 컨텍스트 가져오기
# ==========================================
def get_rag_context_from_functions(function_calls):
    """
    function_calls를 Backend API로 전송하여 RAG 컨텍스트를 가져옵니다.
    
    Args:
        function_calls: Query Agent가 생성한 function_calls 배열
        
    Returns:
        dict: RAG 검색 결과 (chunks, document_titles 등)
        None: API 호출 실패 시
    """
    if not function_calls:
        return None
        
    try:
        # Backend API 호출
        response = requests.post(
            f"{BACKEND_URL}/api/functions/execute",
            json={"function_calls": function_calls},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                print(f"  -> [RAG API] 응답 성공")
                return result.get("results", {})
        
        print(f"  -> [RAG API] 응답 코드: {response.status_code}")
        return None
        
    except requests.exceptions.ConnectionError:
        print(f"  -> [RAG API] 연결 실패 - Backend 서버가 실행 중인지 확인하세요 ({BACKEND_URL})")
        return None
    except requests.exceptions.Timeout:
        print("  -> [RAG API] 타임아웃")
        return None
    except Exception as e:
        print(f"  -> [RAG API 에러] {e}")
        return None


def format_rag_context(rag_results):
    """
    RAG 결과를 프롬프트에 포함할 문자열로 포맷팅합니다.
    """
    if not rag_results:
        return ""
    
    context_parts = []
    
    for key, result in rag_results.items():
        chunks = result.get("chunks", [])
        if not chunks:
            continue
        
        context_parts.append(f"\n=== 관련 입시 정보 ({result.get('university', '전체')}) ===")
        
        for i, chunk in enumerate(chunks[:5], 1):  # 상위 5개 청크만 사용
            content = chunk.get("content", "")[:500]  # 각 청크 500자 제한
            context_parts.append(f"[{i}] {content}")
    
    return "\n".join(context_parts) if context_parts else ""


# ==========================================
# [핵심] 게시글 분석 및 답변 생성
# ==========================================
def analyze_and_generate_reply(title, content, use_rag=True):
    try:
        # Query Agent로 게시글 분석 및 function_calls 생성
        print("  -> [Query Agent] 게시글 분석 중...")
        function_calls = generate_function_calls(title, content)
        
        if function_calls is None:
            # 에러 발생
            print("  -> [Query Agent] 에러 - 기본 PASS 처리")
            return None
        
        if not function_calls:
            # PASS (도움 불필요한 게시글)
            return None
        
        # RAG 컨텍스트 가져오기
        rag_context = ""
        if use_rag:
            print("  -> [RAG] Backend API 호출 중...")
            rag_results = get_rag_context_from_functions(function_calls)
            if rag_results:
                rag_context = format_rag_context(rag_results)
                print(f"  -> [RAG] 컨텍스트 {len(rag_context)}자 로드 완료")
            else:
                print("  -> [RAG] 컨텍스트 없음 (기본 모드로 진행)")
        
        # RAG 컨텍스트 포함 프롬프트 구성
        rag_section = ""
        if rag_context:
            rag_section = f"""
        [📚 관련 입시 정보 (RAG)]
        아래는 게시글과 관련된 공식 입시 정보입니다. 답변 시 참고하세요.
        {rag_context}
        """
        
        prompt = f"""
        당신은 수만휘 입시 커뮤니티의 입시 멘토입니다.
        게시글을 읽고 도움이 되는 댓글을 작성하세요.

        [게시글 정보]
        제목: {title}
        본문: {content[:1000]}
        {rag_section}
        [작성 전략: 철저한 데이터 기반의 컨설팅]

0. **최우선 규칙**
    - 학생의 질문 맥락을 최우선으로 고려해서 대답하세요. 불필요한 정보 인용, 맥락상 어색한 답변은 절대로 하지 마세요.

1. **🎯 핵심 가치 (Value Proposition)**
   - **무조건 '숫자'로 대답:** RAG로 가져온 **'작년 입결(70% 컷)', '환산 점수', '모집 인원 변화'** 등 구체적인 수치를 반드시 하나 이상 인용해.
   - **정시/교과 파이터 모드:** 질문자의 성적이 애매하면 "이 점수면 OO대는 위험하고 △△대가 차라리 낫다"는 식으로 **대안을 제시**하거나 **합격 가능성을 냉정하게 진단**해.
   - **내용:** "유리하다" 같은 모호한 표현 대신, "작년 컷(392점)보다 3점 높아 안정적이에요", "해당 대학에서 가장 낮은 컷(심리학과, 395점)보다 2점 낮아 어려워요."처럼 **수치 중심**으로 설명.

2. **🗣️ 톤앤매너 (Tone & Manner)**
   - **말투:** "~해요"체 사용하되, 자신감 있고 확신에 찬 어조. (친절한 선배 말투, 무례하지 않게.)
   - **길이:** 3~4문장. (서론 빼고 본론만 딱.)

3. **출력 형식:** 댓글 내용만 출력하세요.
   - **다른 말 없이 댓글 내용만 출력하세요**
   - **마크다운 형식(**, ##, > 등) 사용 금지.** 평문(Plain Text)만 사용.
   - **중요** 위 [📚 관련 입시 정보 (RAG)] 블록에 적힌 수치(입결, 컷, 환산점수, 모집인원 등)를 근거로 한 답변이 아닐 경우에는 빈 배열을 반환하세요, 자료에 근거하지 않고 자체 생성하는 댓글은 절대로 달지 마세요.
   - **중요** 생성한 댓글이 명확하게 도움되지 않거나, 학생이 공격적으로 느낄 수 있다고 느껴지면 빈 배열을 반환하세요.
        """
        
        # Answer Agent로 답변 생성 (gemini-3-flash-preview)
        response = answer_agent.generate_content(prompt)
        result = (response.text or "").strip()
        result = result.replace('"', '').replace("'", "")  # 따옴표 제거
        result = result.strip()
        
        # 할 말 없으면 댓글 안 달고 넘어감 (Query Agent와 동일하게 PASS)
        if not result:
            print("  -> [Answer Agent] 할 말 없음 - PASS (댓글 생략)")
            return None
        
        # 고정 형식으로 포맷팅
        formatted_reply = f"""수험생 전문 ai에 물어보니까 이러네요

{result}

구글에 uni2road 검색해서 써 보세요""" 
        
        return formatted_reply
            
    except Exception as e:
        print(f"  -> [AI 에러] {e}")
        return None

# ==========================================
# [기본 함수]
# ==========================================
def load_history():
    if not os.path.exists(HISTORY_FILE): return set()
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f.readlines())
    except: return set()

def append_history(link):
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(link + "\n")
    except: pass

# ==========================================
# [메인 로봇]
# ==========================================
def run_search_bot():
    global should_stop
    
    # 설정 로드
    bot_config = load_bot_config()
    rest_minutes = bot_config.get("rest_minutes", 3)
    cph_min = bot_config.get("comments_per_hour_min")
    cph_max = bot_config.get("comments_per_hour_max")
    if cph_min and cph_max and 0 < cph_min <= cph_max:
        print(f"[봇 설정] 시간당 댓글: {cph_min}~{cph_max}개, 휴식: {rest_minutes}분 (댓글 간 랜덤 딜레이 적용)")
    else:
        min_d = bot_config.get("min_delay_seconds", 50)
        max_d = bot_config.get("max_delay_seconds", 720)
        print(f"[봇 설정] 딜레이: {min_d}-{max_d}초, 휴식: {rest_minutes}분")
    
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    # 서버용 Headless 옵션
    if HEADLESS_MODE:
        print("[봇] Headless 모드로 실행")
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    else:
        chrome_options.add_argument("--start-maximized")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    wait = WebDriverWait(driver, 10) 

    try:
        print("========== [자동 댓글 봇 (서버용)] ==========")
        visited_links = load_history()
        
        # 쿠키 기반 로그인
        if not load_cookies(driver):
            print("[봇] 로그인 실패. 종료합니다.")
            return
        
        print("[봇] 봇 시작! (종료: Ctrl+C 또는 .stop_bot 파일 생성)")

        while not should_stop:
            # 종료 플래그 확인
            if check_stop_flag():
                print("[봇] 정지 플래그 감지, 종료합니다.")
                break
            
            # 설정 리로드 (런타임 변경 반영)
            bot_config = load_bot_config()
            min_delay_sec = bot_config.get("min_delay_seconds", 50)
            cph_min = bot_config.get("comments_per_hour_min")
            cph_max = bot_config.get("comments_per_hour_max")
            rest_minutes = bot_config.get("rest_minutes", 3)
            # 시간당 댓글 수 범위로 랜덤 딜레이 계산 (예: 5~10개/시간 → 360~720초)
            if cph_min and cph_max and 0 < cph_min <= cph_max:
                delay_max = 3600 / cph_min
                delay_min_candidate = 3600 / cph_max
                delay_min = max(min_delay_sec, delay_min_candidate)
                delay_min = min(delay_min, delay_max - 1) if delay_min >= delay_max else delay_min
                delay_max = max(delay_max, delay_min + 1)
            else:
                delay_min = min_delay_sec
                delay_max = bot_config.get("max_delay_seconds", 720)  # 기본 720초(시간당 5개 수준)
            
            for keyword in TARGET_KEYWORDS:
                if should_stop or check_stop_flag():
                    break
                    
                try:
                    encoded = urllib.parse.quote(keyword)
                    search_url = f"https://cafe.naver.com/f-e/cafes/{config.CLUB_ID}/menus/0?viewType=L&ta=ARTICLE_COMMENT&page=1&q={encoded}"
                    
                    print(f"\n>>> 키워드: '{keyword}'")
                    driver.get(search_url)
                    time.sleep(random.uniform(3, 4))
                    
                    all_links = driver.find_elements(By.XPATH, "//a[contains(@href, '/articles/') and not(contains(@class, 'comment'))]")
                    
                    if not all_links: continue

                    target_links = []
                    for a_tag in all_links[:8]:
                        try:
                            raw_link = a_tag.get_attribute('href')
                            clean_link = raw_link.split('?')[0] if '?' in raw_link else raw_link
                            title = a_tag.text.strip()
                            if len(title) > 1: 
                                target_links.append((clean_link, title))
                        except: continue
                    
                    print(f" -> 대상(중복포함): {len(target_links)}개")

                    for link, title in target_links:
                        if should_stop or check_stop_flag():
                            break
                            
                        if link in visited_links:
                            print(f" -> [Skip] 방금 처리한 글입니다. ({title[:10]}...)")
                            continue 
                        
                        try:
                            print(f"\n[분석] {title[:15]}...")
                            driver.get(link)
                            time.sleep(random.uniform(2, 3))
                            
                            try: driver.switch_to.frame("cafe_main")
                            except: pass

                            content = ""
                            try: content = driver.find_element(By.CSS_SELECTOR, "div.se-main-container").text
                            except:
                                try: content = driver.find_element(By.CSS_SELECTOR, "div.ContentRenderer").text
                                except: content = ""
                            
                            ai_reply = analyze_and_generate_reply(title, content)
                            
                            if not ai_reply:
                                print("  -> [PASS] (합격자/광고/무관함)")
                                append_history(link)
                                visited_links.add(link)
                                driver.switch_to.default_content()
                                continue
                                
                            print(f"  -> [작성] {ai_reply[:50]}...")

                            try:
                                inbox = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "comment_inbox")))
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", inbox)
                                inbox.click()
                                time.sleep(1)
                                
                                try: driver.find_element(By.CLASS_NAME, "comment_inbox_text").send_keys(ai_reply)
                                except: driver.switch_to.active_element.send_keys(ai_reply)
                                
                                time.sleep(1)
                                driver.find_element(By.XPATH, "//*[text()='등록']").click()
                                
                                try:
                                    WebDriverWait(driver, 2).until(EC.alert_is_present())
                                    driver.switch_to.alert.accept()
                                    # 댓글 실패 기록
                                    save_comment_history(link, title, ai_reply, success=False)
                                    continue
                                except: pass

                                print("  -> [완료]")
                                append_history(link)
                                visited_links.add(link)
                                
                                # 댓글 성공 기록
                                save_comment_history(link, title, ai_reply, success=True)
                                # 댓글 간 랜덤 딜레이 (설정 리로드로 delay_min/max 반영)
                                bot_config = load_bot_config()
                                min_delay_sec = bot_config.get("min_delay_seconds", 50)
                                cph_min = bot_config.get("comments_per_hour_min")
                                cph_max = bot_config.get("comments_per_hour_max")
                                if cph_min and cph_max and 0 < cph_min <= cph_max:
                                    d_max = 3600 / cph_min
                                    d_min_cand = 3600 / cph_max
                                    d_min = max(min_delay_sec, d_min_cand)
                                    d_min = min(d_min, d_max - 1) if d_min >= d_max else d_min
                                    d_max = max(d_max, d_min + 1)
                                else:
                                    d_min, d_max = min_delay_sec, bot_config.get("max_delay_seconds", 720)
                                delay = random.uniform(d_min, d_max)
                                print(f"  -> 대기 {delay:.0f}초 (랜덤)...")
                                time.sleep(delay)

                            except Exception as e:
                                print(f"  -> [실패] {e}")
                                save_comment_history(link, title, ai_reply, success=False)

                            driver.switch_to.default_content()

                        except Exception as e:
                            print(f"  -> [에러] {e}")
                            driver.switch_to.default_content()
                            time.sleep(2)

                except Exception as e:
                    print(f"  -> [키워드 에러] {e}")
            
            if should_stop:
                break
                
            print(f">>> 휴식 {rest_minutes}분...")
            # 휴식 중에도 종료 플래그 확인
            for _ in range(rest_minutes * 6):  # 10초 단위로 체크
                if should_stop or check_stop_flag():
                    break
                time.sleep(10)

    except KeyboardInterrupt:
        print("\n[봇] 사용자 중단")
    except Exception as e:
        print(f"\n[봇] 예외 발생: {e}")
    finally:
        print("[봇] 브라우저 종료 중...")
        driver.quit()
        print("[봇] 종료 완료")

if __name__ == "__main__":
    run_search_bot()