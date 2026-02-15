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
import copy
from datetime import datetime, timezone, timedelta
import google.generativeai as genai
from openai import AzureOpenAI
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
# [DRY RUN 모드]
# ==========================================
# 환경 변수로 제어: DRY_RUN=true면 댓글을 실제로 달지 않고 생성만 함
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# ==========================================
# [서버용 설정]
# ==========================================
# 스크립트 디렉토리 기준으로 경로 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 카페별 디렉토리 (환경변수로 전달받음, 없으면 SCRIPT_DIR 사용)
CAFE_DIR = os.environ.get("CAFE_DIR", SCRIPT_DIR)
CAFE_ID = os.environ.get("CAFE_ID", "suhui")

# 카페별 config 로드
if CAFE_DIR != SCRIPT_DIR:
    # cafes/{cafe_id}/config.py에서 설정 로드
    cafe_config_path = os.path.join(CAFE_DIR, "config.py")
    if os.path.exists(cafe_config_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cafe_config", cafe_config_path)
        cafe_config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cafe_config)
        # config 모듈의 값들을 덮어쓰기
        for attr in ['NAVER_ID', 'NAVER_PW', 'GEMINI_API_KEY', 'CLUB_ID', 'CAFE_NAME', 'CAFE_URL', 'CAFE_MENU_IDS']:
            if hasattr(cafe_config, attr):
                setattr(config, attr, getattr(cafe_config, attr))
        print(f"[봇] 카페 설정 로드: {CAFE_ID} ({getattr(config, 'CAFE_NAME', 'unknown')})")

# 파일 경로는 카페별 디렉토리 사용
# 쿠키 파일은 환경변수로 전달받거나 카페 디렉토리에서 찾음
COOKIE_FILE = os.environ.get("COOKIE_FILE", os.path.join(CAFE_DIR, "naver_cookies.pkl"))
BOT_CONFIG_FILE = os.path.join(CAFE_DIR, "bot_config.json")
BOT_PROMPTS_FILE = os.path.join(CAFE_DIR, "bot_prompts.json")
COMMENT_HISTORY_FILE = os.path.join(CAFE_DIR, "comment_history.json")
DRY_RUN_HISTORY_FILE = os.path.join(CAFE_DIR, "dry_run_history.json")
SKIP_LINKS_FILE = os.path.join(CAFE_DIR, "skip_links.json")
TRAINING_EXAMPLES_FILE = os.path.join(CAFE_DIR, "training_examples.json")
STOP_FLAG_FILE = os.path.join(CAFE_DIR, ".stop_bot")

# 계정 ID (로그용)
ACCOUNT_ID = os.environ.get("ACCOUNT_ID", "unknown")
print(f"[봇] 계정: {ACCOUNT_ID}, 쿠키: {COOKIE_FILE}")

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


def load_query_prompt():
    """bot_prompts.json에서 Query Agent 프롬프트 로드. 없거나 비어 있으면 기본값."""
    if os.path.exists(BOT_PROMPTS_FILE):
        try:
            with open(BOT_PROMPTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                p = (data.get("query_prompt") or "").strip()
                if p:
                    return p
        except Exception:
            pass
    return DEFAULT_QUERY_PROMPT

def load_answer_prompt():
    """bot_prompts.json에서 Answer Agent 프롬프트 로드. 없거나 비어 있으면 기본값."""
    if os.path.exists(BOT_PROMPTS_FILE):
        try:
            with open(BOT_PROMPTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                p = (data.get("answer_prompt") or "").strip()
                if p:
                    return p
        except Exception:
            pass
    return DEFAULT_ANSWER_PROMPT.strip()


def load_training_examples():
    """training_examples.json에서 학습 예시 로드"""
    if os.path.exists(TRAINING_EXAMPLES_FILE):
        try:
            with open(TRAINING_EXAMPLES_FILE, "r", encoding="utf-8") as f:
                examples = json.load(f)
                return examples
        except Exception as e:
            print(f"  -> [학습 데이터] 로드 실패: {e}")
    return []


def format_training_examples(examples, max_examples=78):
    """학습 예시를 프롬프트용 문자열로 포맷팅 (전체 78개 사용)"""
    if not examples:
        return ""
    
    # 전체 사용 (78개 이하면 전부, 초과하면 랜덤 선택)
    if len(examples) <= max_examples:
        selected = examples
    else:
        selected = random.sample(examples, max_examples)
    
    formatted_parts = []
    for i, ex in enumerate(selected, 1):
        title = ex.get("post_title", "")
        comment = ex.get("output_comment", "")
        if title and comment and len(comment) > 30:
            formatted_parts.append(f"[예시 {i}]\n질문: {title}\n답변: {comment}")
    
    return "\n\n".join(formatted_parts)


# ==========================================
# [학습 데이터] comment_history.json에서 실시간 로드
# ==========================================
# 학습 데이터 공유 카페 목록 (수만휘, 수험생카페, 맘카페)
SHARED_TRAINING_CAFES = ["suhui", "pnmath", "gangmok"]

def load_comment_history_for_training():
    """
    여러 카페의 comment_history.json에서 학습용 데이터 로드 (원본 훼손 없이 복사하여 사용)
    - 수만휘, 수험생카페, 맘카페의 학습 데이터를 공유하여 사용
    """
    all_history = []
    cafes_dir = os.path.join(SCRIPT_DIR, "cafes")
    
    for cafe_id in SHARED_TRAINING_CAFES:
        history_file = os.path.join(cafes_dir, cafe_id, "comment_history.json")
        if not os.path.exists(history_file):
            continue
        
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            # 원본 훼손 방지: 깊은 복사 후 추가
            all_history.extend(copy.deepcopy(history))
        except Exception as e:
            print(f"  -> [학습 데이터] {cafe_id} comment_history 로드 실패: {e}")
            continue
    
    print(f"  -> [학습 데이터] 총 {len(all_history)}개 로드 (카페: {', '.join(SHARED_TRAINING_CAFES)})")
    return all_history


def get_answer_agent_examples(max_good=5, max_bad=5):
    """
    Answer Agent용 학습 예시 가져오기
    - 좋은 예시: 게시완료(posted), 승인됨(approved) 중 랜덤 5개
    - 나쁜 예시: 취소됨(cancelled) 중 cancel_reason이 '최종답변부실'인 것만 랜덤 5개
    - intro/outro는 제거하고 본문만 학습 데이터로 사용
    
    Returns:
        tuple: (good_examples, bad_examples)
    """
    history = load_comment_history_for_training()
    
    def strip_intro_outro(comment):
        """댓글에서 intro(첫 줄)와 outro(마지막 줄)를 제거하고 본문만 반환"""
        if not comment:
            return comment
        
        # 빈 줄 기준으로 분리
        paragraphs = comment.strip().split('\n\n')
        
        # 3개 이상의 단락이 있으면 첫 번째와 마지막 제거
        if len(paragraphs) >= 3:
            # 중간 단락들만 반환
            return '\n\n'.join(paragraphs[1:-1])
        elif len(paragraphs) == 2:
            # 2개면 첫 번째만 제거 (마지막은 본문일 수 있음)
            return paragraphs[1]
        else:
            # 1개면 그대로 반환
            return comment
    
    # 상태별 분류
    good_examples = []  # posted, approved
    bad_examples = []   # cancelled with reason '최종답변부실'
    
    for item in history:
        status = item.get("status", "")
        cancel_reason = item.get("cancel_reason", "")
        post_content = item.get("post_content", "") or item.get("post_title", "")
        comment = item.get("comment", "")
        
        if not post_content or not comment:
            continue
        
        # intro/outro 제거한 본문만 사용
        comment_body = strip_intro_outro(comment)
        
        example = {
            "post_content": post_content[:500],  # 원글 (500자 제한)
            "comment": comment_body  # 최종답변 (intro/outro 제거)
        }
        
        if status in ["posted", "approved"]:
            good_examples.append(example)
        elif status == "cancelled" and cancel_reason == "최종답변부실":
            # 나쁜 예시는 '최종답변부실' 사유가 있는 것만
            bad_examples.append(example)
    
    # 랜덤 선택
    selected_good = random.sample(good_examples, min(max_good, len(good_examples))) if good_examples else []
    selected_bad = random.sample(bad_examples, min(max_bad, len(bad_examples))) if bad_examples else []
    
    print(f"  -> [학습 데이터] 좋은 예시 {len(selected_good)}개, 나쁜 예시(최종답변부실) {len(selected_bad)}개 로드 (intro/outro 제거됨)")
    
    return selected_good, selected_bad


def format_answer_agent_examples(good_examples, bad_examples):
    """Answer Agent용 학습 예시를 프롬프트 문자열로 포맷팅"""
    parts = []
    
    # 좋은 예시 (따라해야 할 것)
    if good_examples:
        parts.append("=" * 50)
        parts.append("[✅ 따라해야 할 좋은 답변 예시]")
        parts.append("아래는 승인되어 실제로 게시된 답변입니다.")
        parts.append("특징: 3~4문장, 구체적인 숫자(입결, 모집인원 등) 인용, ~해요체")
        parts.append("=" * 50)
        for i, ex in enumerate(good_examples, 1):
            parts.append(f"\n[좋은 예시 {i}]")
            parts.append(f"원글: {ex['post_content']}")
            parts.append(f"답변: {ex['comment']}")
    
    # 나쁜 예시 (따라하면 안 되는 것)
    if bad_examples:
        parts.append("\n" + "=" * 50)
        parts.append("[❌ 따라하면 안 되는 나쁜 답변 예시]")
        parts.append("아래는 취소된 답변입니다. 이런 식으로 작성하지 마세요.")
        parts.append("문제점: 너무 김, 마크다운 사용, 번호 목록 사용, RAG 데이터 없이 일반적 조언")
        parts.append("=" * 50)
        for i, ex in enumerate(bad_examples, 1):
            parts.append(f"\n[나쁜 예시 {i}]")
            parts.append(f"원글: {ex['post_content']}")
            parts.append(f"답변: {ex['comment']}")
    
    return "\n".join(parts)


def get_query_agent_examples(max_examples=10):
    """
    Query Agent용 학습 예시 가져오기
    - 취소됨(cancelled) 중 cancel_reason이 '부적절한 글'인 것 랜덤 10개
    - 원글만 전달 (이런 글에는 답변하지 말라는 의미)
    
    Returns:
        list: 부적절한 글 예시 목록
    """
    history = load_comment_history_for_training()
    
    inappropriate_posts = []
    
    for item in history:
        status = item.get("status", "")
        cancel_reason = item.get("cancel_reason", "")
        post_content = item.get("post_content", "") or item.get("post_title", "")
        
        if status == "cancelled" and cancel_reason == "부적절한 글" and post_content:
            inappropriate_posts.append({
                "post_content": post_content[:500]  # 원글 (500자 제한)
            })
    
    # 랜덤 선택
    selected = random.sample(inappropriate_posts, min(max_examples, len(inappropriate_posts))) if inappropriate_posts else []
    
    print(f"  -> [Query Agent 학습] 부적절한 글 예시 {len(selected)}개 로드")
    
    return selected


def format_query_agent_examples(inappropriate_posts):
    """Query Agent용 학습 예시를 프롬프트 문자열로 포맷팅"""
    if not inappropriate_posts:
        return ""
    
    parts = []
    parts.append("\n" + "=" * 50)
    parts.append("[❌ 답변하면 안 되는 부적절한 글 예시]")
    parts.append("아래와 같은 글에는 PASS 처리하세요. (빈 배열 반환)")
    parts.append("=" * 50)
    
    for i, ex in enumerate(inappropriate_posts, 1):
        parts.append(f"\n[부적절한 글 {i}]")
        parts.append(f"원글: {ex['post_content']}")
    
    return "\n".join(parts)


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

def save_comment_history(post_url, post_title, comment_content, success=True,
                         post_content=None, query=None, function_result=None,
                         status="pending", comment_id=None):
    """댓글 기록 저장 (반자동 시스템용)
    
    Args:
        status: pending(대기중), approved(승인됨), cancelled(취소됨), posted(게시완료)
        comment_id: 고유 ID (없으면 자동 생성)
    """
    import uuid
    
    # 가실행 모드는 별도 파일에 기록
    if DRY_RUN:
        history_file = DRY_RUN_HISTORY_FILE
    else:
        history_file = COMMENT_HISTORY_FILE
    
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            history = []
    
    now = datetime.now().isoformat()
    record = {
        "id": comment_id or str(uuid.uuid4()),
        "timestamp": now,
        "post_url": post_url,
        "post_title": post_title,
        "comment": comment_content,
        "success": success,
        "dry_run": DRY_RUN,
        "status": status,
        "action_history": [{"action": "created", "timestamp": now}],
        "posted_at": None
    }
    if post_content is not None:
        record["post_content"] = post_content
    if query is not None:
        record["query"] = query
    if function_result is not None:
        record["function_result"] = function_result
    history.append(record)
    
    # 최근 500개만 유지
    if len(history) > 500:
        history = history[-500:]
    
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    
    return record["id"]

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
HISTORY_FILE = os.path.join(CAFE_DIR, "visited_history.txt")

# AI 모델 제공자 설정 (gemini 또는 azure)
AI_MODEL_PROVIDER = getattr(config, 'AI_MODEL_PROVIDER', 'gemini')

# Azure OpenAI 설정 (config.py 또는 환경변수에서 로드)
AZURE_OPENAI_ENDPOINT = getattr(config, 'AZURE_OPENAI_ENDPOINT', '') or os.getenv('AZURE_OPENAI_ENDPOINT', '')
AZURE_OPENAI_API_KEY = getattr(config, 'AZURE_OPENAI_API_KEY', '') or os.getenv('AZURE_OPENAI_API_KEY', '')
AZURE_OPENAI_API_VERSION = getattr(config, 'AZURE_OPENAI_API_VERSION', '2024-02-15-preview')
AZURE_OPENAI_DEPLOYMENT = getattr(config, 'AZURE_OPENAI_DEPLOYMENT', 'gpt-5.2-chat-4')

# bot_config.json에서 모델 설정 로드 (런타임 변경 지원)
def load_model_config():
    """bot_config.json에서 AI 모델 설정 로드"""
    global AI_MODEL_PROVIDER
    if os.path.exists(BOT_CONFIG_FILE):
        try:
            with open(BOT_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                provider = data.get("ai_model_provider", "").strip()
                if provider in ["gemini", "azure"]:
                    return provider
        except Exception:
            pass
    return AI_MODEL_PROVIDER

# Azure OpenAI 클라이언트 초기화
azure_client = None
if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY:
    try:
        azure_client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION
        )
        print(f"[INFO] Azure OpenAI 클라이언트 초기화 완료 (배포: {AZURE_OPENAI_DEPLOYMENT})")
    except Exception as e:
        print(f"[WARNING] Azure OpenAI 클라이언트 초기화 실패: {e}")
        azure_client = None

# Gemini API 설정
genai.configure(api_key=config.GEMINI_API_KEY)

# Query Agent (RAG 검색 쿼리 생성용)
query_agent_gemini = None
try:
    query_agent_gemini = genai.GenerativeModel('gemini-2.5-flash-lite')
    print("[INFO] Query Agent (Gemini): gemini-2.5-flash-lite")
except:
    try:
        query_agent_gemini = genai.GenerativeModel('gemini-2.0-flash')
        print("[INFO] Query Agent (Gemini): gemini-2.0-flash (fallback)")
    except:
        print("[WARNING] Gemini Query Agent 초기화 실패")

# Answer Agent (답변 생성용)
answer_agent_gemini = None
try:
    answer_agent_gemini = genai.GenerativeModel('gemini-2.5-flash-lite')
    print("[INFO] Answer Agent (Gemini): gemini-2.5-flash-lite")
except:
    try:
        answer_agent_gemini = genai.GenerativeModel('gemini-2.0-flash')
        print("[INFO] Answer Agent (Gemini): gemini-2.0-flash (fallback)")
    except:
        print("[WARNING] Gemini Answer Agent 초기화 실패")

# 현재 사용 중인 모델 표시
current_provider = load_model_config()
print(f"[INFO] 현재 AI 모델 제공자: {current_provider.upper()}")


def call_ai_model(prompt, is_json_response=False, temperature=0.3, max_tokens=2048):
    """
    AI 모델 호출 (Gemini 또는 Azure OpenAI)
    
    Args:
        prompt: 프롬프트 문자열
        is_json_response: JSON 응답 여부 (Query Agent용)
        temperature: 온도 설정
        max_tokens: 최대 토큰 수
    
    Returns:
        str: AI 응답 텍스트
        None: 에러 발생 시
    """
    provider = load_model_config()
    
    if provider == "azure" and azure_client:
        try:
            messages = [{"role": "user", "content": prompt}]
            
            response = azure_client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_tokens,
                response_format={"type": "json_object"} if is_json_response else None
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"  -> [Azure OpenAI 에러] {e}")
            # Fallback to Gemini
            if query_agent_gemini or answer_agent_gemini:
                print("  -> [Fallback] Gemini로 전환...")
                provider = "gemini"
            else:
                return None
    
    if provider == "gemini":
        try:
            agent = query_agent_gemini if is_json_response else answer_agent_gemini
            if not agent:
                print("  -> [에러] Gemini 모델이 초기화되지 않음")
                return None
            
            generation_config = {
                "temperature": temperature,
                "max_output_tokens": max_tokens
            }
            if is_json_response:
                generation_config["response_mime_type"] = "application/json"
            
            response = agent.generate_content(prompt, generation_config=generation_config)
            return (response.text or "").strip()
        except Exception as e:
            print(f"  -> [Gemini 에러] {e}")
            return None
    
    print(f"  -> [에러] 알 수 없는 AI 제공자: {provider}")
    return None


# 레거시 호환성을 위한 변수 (기존 코드에서 사용)
query_agent = query_agent_gemini
answer_agent = answer_agent_gemini

# 기본 키워드 (bot_config.json에 없을 때 사용)
DEFAULT_KEYWORDS = [
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

    # 3. 기타 키워드
    "까요", "vs", "가능", "어디", "봐주", "조언", "상담"
]

def load_keywords():
    """bot_config.json에서 검색 키워드 로드. 없거나 비어 있으면 기본값 사용."""
    if os.path.exists(BOT_CONFIG_FILE):
        try:
            with open(BOT_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                keywords = data.get("keywords", [])
                if keywords and len(keywords) > 0:
                    return keywords
        except Exception:
            pass
    return DEFAULT_KEYWORDS


def load_banned_keywords():
    """bot_config.json에서 금지 키워드 로드. 없으면 빈 리스트 반환."""
    if os.path.exists(BOT_CONFIG_FILE):
        try:
            with open(BOT_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("banned_keywords", [])
        except Exception:
            pass
    return []


def contains_banned_keyword(title, content, banned_keywords):
    """제목이나 본문에 금지 키워드가 포함되어 있는지 확인"""
    if not banned_keywords:
        return False
    
    text = (title or "") + " " + (content or "")
    text = text.lower()
    
    for keyword in banned_keywords:
        if keyword.lower() in text:
            return True
    return False

# Backend API URL (config에서 가져오기, 기본값: 로컬)
BACKEND_URL = getattr(config, 'BACKEND_URL', 'http://localhost:8000')

# ==========================================
# [오프닝/클로징 멘트] 랜덤 선택
# ==========================================

# 오프닝: "AI한테 물어보니까 이렇다" (초간단 버전)
OPENINGS = []

# 클로징: "구글에 uni2road 검색해라" (초간단 버전)
CLOSINGS = []

# ==========================================
# [Query Agent] 게시글 분석 및 RAG 검색 쿼리 생성 (gemini-2.5-flash-lite)
# ==========================================
QUERY_AGENT_PROMPT = """당신은 대학 입시 커뮤니티 게시글을 분석하는 **Query Agent**입니다.

## 역할
게시글을 읽고 **도움이 필요한 수험생의 질문**인지 판단한 후, 필요시 RAG 검색을 위한 함수 호출을 생성하세요.
당신의 역할은 정보 검색을 위한 json 형식의 함수 호출입니다. 당신이 찾은 정보와 대화의 맥락을 종합하여 main agent가 최종적인 답변을 생성합니다.
아래에 명시된 출력 형식을 지키세요. 정확한 함수를 올바르게 호출하여 정보를 검색하세요.

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

# Query Agent 기본 프롬프트 (관리 페이지에서 수정 가능)
DEFAULT_QUERY_PROMPT = QUERY_AGENT_PROMPT.strip()

# Answer Agent 기본 프롬프트 (관리 페이지에서 수정 가능)
DEFAULT_ANSWER_PROMPT = """
[작성 전략: 철저한 데이터 기반의 컨설팅]

0. **최우선 규칙**
    - 학생의 질문 맥락을 최우선으로 고려해서 대답하세요. 불필요한 정보 인용, 맥락상 어색한 답변은 절대로 하지 마세요.
    - 학생의 점수(원점수, 백분위, 등급 등)은 본문에 있는 점수만 인용하세요, [📚 관련 입시 정보 (RAG)]에서 환산된 백분위는 절대 인용하지 마세요, 대학별 환산 점수만 인용해도 됩니다.

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

def generate_function_calls(title, content, existing_comments=""):
    """
    Query Agent로 게시글 분석 및 함수 호출 생성
    
    Args:
        title: 게시글 제목
        content: 게시글 본문
        existing_comments: 기존 댓글 목록 (중복 체크용)
    
    Returns:
        list: function_calls 배열 (PASS인 경우 빈 배열)
        None: 에러 발생 시
    """
    try:
        query_instruction = load_query_prompt()
        
        # 부적절한 글 예시 로드 (취소됨 중 '부적절한 글' 사유)
        inappropriate_posts = get_query_agent_examples(max_examples=20)
        inappropriate_section = format_query_agent_examples(inappropriate_posts)
        
        # 기존 댓글 섹션 (중복 방지 체크)
        existing_comments_section = ""
        if existing_comments:
            existing_comments_section = f"""
[⚠️ 기존 댓글 - 중복 방지 체크]
아래는 이 게시글에 이미 달린 댓글들입니다.
만약 "uni2road", "입시 ai", "수험생 ai", "구글에 uni2road" 등 우리 봇이 단 것으로 보이는 댓글이 있다면,
반드시 빈 배열을 반환하세요. 중복 댓글은 절대 금지입니다.
특히 "하늘담아", "도군" 닉네임의 댓글이 있으면 무조건 빈 배열 반환!

{existing_comments[:300]}
"""
        
        prompt = f"""{query_instruction}
{inappropriate_section}
{existing_comments_section}

[게시글]
제목: {title}
본문: {content[:1000]}

위 게시글을 분석하여 function_calls를 JSON 형식으로 생성하세요.
⚠️ 중요: 기존 댓글에 이미 우리 봇의 댓글이 있다면 빈 배열 {{"function_calls": []}}을 반환하세요.
"""
        
        # 새로운 통합 AI 호출 함수 사용
        result_text = call_ai_model(prompt, is_json_response=True, temperature=1.0, max_tokens=2048)
        
        if not result_text:
            print(f"  -> [Query Agent] AI 응답 없음")
            return None
        
        # JSON 파싱
        result = json.loads(result_text)
        function_calls = result.get("function_calls", [])
        
        if not function_calls:
            print(f"  -> [Query Agent] PASS (도움 불필요 또는 이미 댓글 있음)")
            return []
        
        print(f"  -> [Query Agent] {len(function_calls)}개 함수 호출 생성")
        for call in function_calls:
            print(f"     - {call.get('function')}: {call.get('params', {}).get('university', '')} {call.get('params', {}).get('query', '')[:50]}")
        
        return function_calls
        
    except json.JSONDecodeError as e:
        print(f"  -> [Query Agent] JSON 파싱 실패: {e}")
        print(f"     원본: {result_text[:200] if result_text else 'None'}")
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
        print("  -> [RAG] rag_results가 비어있음")
        return "[검색 결과 없음]"
    
    context_parts = []
    total_chunks = 0
    
    print(f"  -> [RAG DEBUG] rag_results keys: {list(rag_results.keys())}")
    
    for key, result in rag_results.items():
        chunks = result.get("chunks", [])
        total_chunks += len(chunks)
        print(f"  -> [RAG DEBUG] {key}: {len(chunks)}개 청크")
        
        if not chunks:
            # 검색했지만 결과가 없는 경우도 표시
            context_parts.append(f"\n=== {result.get('university', '전체')} ===\n[검색 결과 없음]")
            continue
        
        # 첫 번째 청크 구조 확인
        if chunks:
            first_chunk = chunks[0]
            print(f"  -> [RAG DEBUG] 첫 청크 keys: {list(first_chunk.keys())}")
            print(f"  -> [RAG DEBUG] 첫 청크 content 길이: {len(first_chunk.get('content', ''))}")
        
        context_parts.append(f"\n=== 관련 입시 정보 ({result.get('university', '전체')}) ===")
        
        for i, chunk in enumerate(chunks[:10], 1):  # 상위 10개 청크 사용
            content = chunk.get("content", "")  # 전체 내용 전달 (제한 제거)
            context_parts.append(f"[{i}] {content}")
    
    if not context_parts:
        return "[검색 결과 없음]"
    
    final_context = "\n".join(context_parts)
    print(f"  -> [RAG DEBUG] 최종 컨텍스트 길이: {len(final_context)}자")
    return final_context


# ==========================================
# [핵심] 게시글 분석 및 답변 생성
# ==========================================
def analyze_and_generate_reply(title, content, use_rag=True, existing_comments=""):
    """게시글 분석 및 답변 생성
    
    Args:
        title: 게시글 제목
        content: 게시글 본문
        use_rag: RAG 사용 여부
        existing_comments: 기존 댓글 목록 (AI 더블체크용)
    """
    try:
        # Query Agent로 게시글 분석 및 function_calls 생성
        print("  -> [Query Agent] 게시글 분석 중...")
        function_calls = generate_function_calls(title, content, existing_comments=existing_comments)
        
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
            rag_section = f"""[📚 관련 입시 정보 (RAG)]
아래는 게시글과 관련된 공식 입시 정보입니다. 답변 시 참고하세요.
{rag_context}
"""
        
        instruction = load_answer_prompt()
        
        # ==========================================
        # 학습 데이터 로드 (comment_history.json에서 실시간)
        # - 좋은 예시: 게시완료/승인됨 중 10개
        # - 나쁜 예시: 취소됨 중 10개
        # ==========================================
        good_examples, bad_examples = get_answer_agent_examples(max_good=10, max_bad=10)
        examples_section = format_answer_agent_examples(good_examples, bad_examples)
        
        instruction = load_answer_prompt()
        
        # 기존 댓글 섹션 (AI 더블체크용)
        existing_comments_section = ""
        if existing_comments:
            existing_comments_section = f"""
[⚠️ 기존 댓글 목록 - 중복 방지 체크]
아래는 이 게시글에 이미 달린 댓글들입니다.
만약 아래 댓글 중 "uni2road", "입시 ai", "수험생 ai" 등 우리 봇이 단 것으로 보이는 댓글이 있거나,
"하늘담아", "도군" 닉네임의 댓글이 있다면 반드시 빈 문자열을 반환하세요. 
중복 댓글은 절대 금지입니다.

{existing_comments[:500]}
"""
        
        # 프롬프트 순서: 1.사용자정의 → 2.학습예시 → 3.게시글 → 4.RAG
        prompt = f"""[✍️ 작성 지침 및 역할]
{instruction}

{examples_section}

[📋 게시글 정보]
제목: {title}
본문: {content[:1000]}
{existing_comments_section}
{rag_section}

⚠️ 중요: 기존 댓글에 이미 우리 봇(uni2road, 입시 ai, 하늘담아, 도군)의 댓글이 있다면 빈 문자열만 반환하세요.
"""
        print(f"  -> [Answer Agent] 학습 데이터 로드 (좋은 예시 {len(good_examples)}개, 나쁜 예시 {len(bad_examples)}개)")
        
        # 새로운 통합 AI 호출 함수 사용
        result = call_ai_model(prompt, is_json_response=False, temperature=1.0, max_tokens=2048)
        
        if not result:
            print(f"  -> [Answer Agent] AI 응답 없음 - PASS")
            return None
        
        result = result.replace('"', '').replace("'", "")  # 따옴표 제거
        result = result.strip()
        
        # 할 말 없거나 20자 이하면 댓글 안 달고 넘어감 (빈 배열/짧은 무의미 응답 차단)
        if not result or len(result) <= 20:
            print(f"  -> [Answer Agent] 할 말 없음/짧음 ({len(result)}자) - PASS (댓글 생략)")
            return None
        
        # 랜덤 오프닝/클로징 선택 (비어있으면 사용 안함)
        opening = random.choice(OPENINGS) if OPENINGS else ""
        closing = random.choice(CLOSINGS) if CLOSINGS else ""
        
        # 고정 형식으로 포맷팅
        if opening and closing:
            formatted_reply = f"""{opening}

{result}

{closing}"""
        elif opening:
            formatted_reply = f"""{opening}

{result}"""
        elif closing:
            formatted_reply = f"""{result}

{closing}"""
        else:
            formatted_reply = result 
        
        # 관리 페이지 5열(원글/쿼리/함수결과/최종답변/링크) 저장용
        # 함수결과 = RAG 컨텍스트만 (함수 출력값)
        extra = {
            "post_content": (title or "") + "\n\n" + (content or "")[:2000],
            "query": json.dumps(function_calls, ensure_ascii=False),
            "function_result": rag_context or ""
        }
        return (formatted_reply, extra)
            
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
    """방문 기록 추가 (중복 방지) - 가실행 모드는 기록 안 함
    
    ⚠️ 중요: 이 함수는 글 분석 전에 호출되어야 Race Condition을 방지할 수 있음
    """
    # 가실행 모드는 visited_history에 기록하지 않음
    if DRY_RUN:
        return
    
    try:
        import fcntl  # 파일 락용
        
        # article ID 추출하여 정규화된 형태로 저장
        article_id = extract_article_id(link)
        
        # 파일 락을 사용하여 동시 쓰기 방지
        with open(HISTORY_FILE, "a+", encoding="utf-8") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # 배타적 락 획득
                
                # 파일 처음으로 이동하여 기존 내용 확인
                f.seek(0)
                existing_ids = set()
                for line in f:
                    stored_url = line.strip()
                    if stored_url:
                        stored_id = extract_article_id(stored_url) or stored_url
                        existing_ids.add(stored_id)
                
                # 중복 체크 (article ID 기준)
                check_id = article_id if article_id else link
                if check_id in existing_ids:
                    return  # 이미 있으면 추가하지 않음
                
                # 파일 끝으로 이동하여 추가
                f.seek(0, 2)  # SEEK_END
                f.write(link + "\n")
                f.flush()
                
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # 락 해제
                
    except ImportError:
        # fcntl이 없는 환경 (Windows 등)에서는 기존 방식 사용
        try:
            existing = load_history()
            if link in existing:
                return
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(link + "\n")
        except:
            pass
    except Exception as e:
        print(f"  -> [경고] 히스토리 기록 실패: {e}")
        # 실패해도 계속 진행 (중복 댓글보다는 나음)


def extract_article_id(url):
    """URL에서 article ID 추출 (다양한 형식 지원)
    
    지원 형식:
    - https://cafe.naver.com/f-e/cafes/10197921/articles/29429119
    - https://cafe.naver.com/suhui/29429119
    - https://cafe.naver.com/suhui/29429119?art=...
    """
    import re
    # 숫자만 추출 (마지막 숫자 그룹이 article ID)
    # f-e 형식: /articles/29429119
    match = re.search(r'/articles/(\d+)', url)
    if match:
        return match.group(1)
    
    # 일반 형식: /카페명/29429119 또는 /카페명/29429119?...
    match = re.search(r'/([a-zA-Z0-9_]+)/(\d+)(?:\?|$)', url)
    if match:
        return match.group(2)
    
    return None


def check_post_date(driver, min_year=2026, min_month=2):
    """게시글 작성 날짜가 최소 날짜 이후인지 확인
    
    Args:
        driver: Selenium WebDriver
        min_year: 최소 연도 (기본값: 2026)
        min_month: 최소 월 (기본값: 2)
        
    Returns:
        bool: 최소 날짜 이후면 True, 이전이면 False
    """
    try:
        # 네이버 카페 게시글 날짜 셀렉터들
        date_selectors = [
            "span.date",  # 일반적인 날짜 표시
            "span.article_info span",  # 게시글 정보 내 날짜
            "div.article_info span.date",
            "span.WriterInfo__date--mYIJg",  # 새 UI
            "div.ArticleWriterInfo span.date",
            "span.se_publishDate",
        ]
        
        date_text = None
        for selector in date_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for elem in elements:
                    text = elem.text.strip()
                    # 날짜 형식 확인 (YYYY.MM.DD 또는 YY.MM.DD 또는 MM.DD 등)
                    if text and ('.' in text or '-' in text or '/' in text):
                        date_text = text
                        break
                if date_text:
                    break
            except:
                continue
        
        if not date_text:
            # 날짜를 찾지 못하면 일단 처리 (안전하게)
            print("  -> [날짜] 날짜 정보를 찾을 수 없음 (처리 진행)")
            return True
        
        # 날짜 파싱
        import re
        
        # "2026.02.08" 또는 "26.02.08" 또는 "2026-02-08" 형식
        match = re.search(r'(\d{2,4})[.\-/](\d{1,2})[.\-/](\d{1,2})', date_text)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            
            # 2자리 연도 처리
            if year < 100:
                year += 2000
            
            # 최소 날짜 이후인지 확인
            if year > min_year:
                return True
            elif year == min_year and month >= min_month:
                return True
            else:
                print(f"  -> [PASS] 오래된 글입니다. ({year}.{month:02d})")
                return False
        
        # "2월 8일" 또는 "02.08" 형식 (올해로 가정)
        match = re.search(r'(\d{1,2})[월.\-/]\s*(\d{1,2})', date_text)
        if match:
            month = int(match.group(1))
            # 현재 연도로 가정
            current_year = datetime.now().year
            if current_year >= min_year and month >= min_month:
                return True
            elif current_year > min_year:
                return True
            else:
                print(f"  -> [PASS] 오래된 글입니다. ({current_year}.{month:02d})")
                return False
        
        # 파싱 실패시 일단 처리
        print(f"  -> [날짜] 날짜 파싱 실패: {date_text} (처리 진행)")
        return True
        
    except Exception as e:
        # 에러 발생시 일단 처리
        print(f"  -> [날짜] 날짜 확인 오류: {e} (처리 진행)")
        return True


def check_my_comment_exists(driver, my_nicknames=None):
    """게시글 페이지에서 내 댓글이 이미 있는지 확인
    
    Args:
        driver: Selenium WebDriver
        my_nicknames: 내 닉네임 목록 (없으면 config에서 가져옴)
        
    Returns:
        bool: 내 댓글이 있으면 True
    """
    # 닉네임 목록 가져오기
    if my_nicknames is None:
        # config에서 닉네임 목록 가져오기 (MY_NICKNAMES 우선, 없으면 MY_NICKNAME)
        my_nicknames = getattr(config, 'MY_NICKNAMES', None)
        if not my_nicknames:
            single_nickname = getattr(config, 'MY_NICKNAME', None)
            if single_nickname:
                my_nicknames = [single_nickname]
            else:
                # 닉네임이 설정되지 않은 경우 NAVER_ID 사용
                my_nicknames = [getattr(config, 'NAVER_ID', '')]
    
    # 문자열이면 리스트로 변환
    if isinstance(my_nicknames, str):
        my_nicknames = [my_nicknames]
    
    if not my_nicknames or not any(my_nicknames):
        return False
    
    try:
        # 댓글 영역에서 닉네임 찾기
        comment_authors = driver.find_elements(By.CSS_SELECTOR, "span.comment_nickname, a.comment_nickname, span.nick, a.nick")
        
        for author in comment_authors:
            author_text = author.text.strip()
            for nickname in my_nicknames:
                if nickname and (nickname in author_text or author_text in nickname):
                    print(f"  -> [Skip] 이미 내 댓글이 있음 (닉네임: {author_text})")
                    return True
        
        # 추가: 댓글 작성자 링크에서 ID 확인
        comment_author_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='memberid=']")
        for link in comment_author_links:
            href = link.get_attribute('href') or ''
            if f"memberid={config.NAVER_ID}" in href:
                print(f"  -> [Skip] 이미 내 댓글이 있음 (ID: {config.NAVER_ID})")
                return True
                
    except Exception as e:
        print(f"  -> [경고] 댓글 확인 중 오류: {e}")
    
    return False


def is_already_commented(link):
    """visited_history.txt, comment_history.json, skip_links.json에서 이미 처리한 글인지 확인"""
    # 가실행 모드에서는 중복 체크 안 함
    if DRY_RUN:
        return False
    
    # 입력 링크에서 article ID 추출
    input_article_id = extract_article_id(link)
    if not input_article_id:
        # ID 추출 실패 시 원본 비교
        input_article_id = link
    
    # 0. visited_history.txt 체크 (가장 먼저! - 이 파일이 가장 빠르게 기록됨)
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    stored_url = line.strip()
                    if not stored_url:
                        continue
                    stored_article_id = extract_article_id(stored_url) or stored_url
                    if stored_article_id == input_article_id:
                        print(f"  -> [Skip] visited_history.txt에 이미 있음")
                        return True
        except:
            pass
    
    # 1. comment_history.json 체크
    if os.path.exists(COMMENT_HISTORY_FILE):
        try:
            with open(COMMENT_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
                for item in history:
                    stored_url = item.get("post_url", "")
                    stored_article_id = extract_article_id(stored_url) or stored_url
                    
                    # article ID로 비교 (status와 관계없이 처리된 적 있으면 스킵)
                    # pending, approved, posted, cancelled 모두 중복으로 처리
                    if stored_article_id == input_article_id:
                        status = item.get("status", "unknown")
                        print(f"  -> [Skip] comment_history.json에 이미 있음 (status: {status})")
                        return True
        except:
            pass
    
    # 2. skip_links.json 체크 (수동 스킵 링크)
    if os.path.exists(SKIP_LINKS_FILE):
        try:
            with open(SKIP_LINKS_FILE, "r", encoding="utf-8") as f:
                skip_links = json.load(f)
                for item in skip_links:
                    if item.get("article_id") == input_article_id:
                        print(f"  -> [Skip] 수동 스킵 링크입니다.")
                        return True
        except:
            pass
    
    return False

# ==========================================
# [크롤러 봇] - 반자동 시스템: 댓글 생성만 하고 pending 상태로 저장
# ==========================================
def run_search_bot():
    """크롤러 봇: 게시글을 빠르게 탐색하고 댓글을 생성하여 pending 상태로 저장"""
    global should_stop
    
    # 설정 로드
    bot_config = load_bot_config()
    rest_minutes = bot_config.get("rest_minutes", 3)
    print(f"[크롤러] 반자동 모드 - 댓글 생성만 하고 실제 게시하지 않음")
    
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    # 서버용 Headless 옵션
    if HEADLESS_MODE:
        print("[봇] Headless 모드로 실행")
        
        # PID 기반 고유 user-data-dir 생성 (Chrome crash 방지)
        user_data_dir = os.path.join(SCRIPT_DIR, f"chrome_data_{os.getpid()}")
        os.makedirs(user_data_dir, exist_ok=True)
        print(f"[봇] Chrome user-data-dir: {user_data_dir}")
        
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-software-rasterizer")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-setuid-sandbox")
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-features=VizDisplayCompositor")
        chrome_options.add_argument("--disable-background-networking")
        chrome_options.add_argument("--disable-default-apps")
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
        
        print("[크롤러] 봇 시작! (종료: Ctrl+C 또는 .stop_bot 파일 생성)")
        print("=" * 60)
        print("[반자동 모드] 댓글을 생성하여 대기열에 저장합니다")
        print("=" * 60)

        while not should_stop:
            # 종료 플래그 확인
            if check_stop_flag():
                print("[봇] 정지 플래그 감지, 종료합니다.")
                break
            
            # 설정 리로드 (런타임 변경 반영)
            bot_config = load_bot_config()
            rest_minutes = bot_config.get("rest_minutes", 3)
            
            # 검색할 게시판(메뉴) ID: 없으면 전체(0)
            menu_ids = getattr(config, "CAFE_MENU_IDS", None) or [0]
            if not menu_ids:
                menu_ids = [0]
            
            # 키워드 로드 (매 사이클마다 새로 로드하여 실시간 반영)
            keywords = load_keywords()
            banned_keywords = load_banned_keywords()
            print(f"[INFO] 검색 키워드 {len(keywords)}개, 금지 키워드 {len(banned_keywords)}개 로드됨")
            
            # 멀티 카페 설정 로드 (없으면 현재 카페만)
            multi_cafes = getattr(config, "MULTI_CAFES", None)
            if not multi_cafes:
                multi_cafes = [{"club_id": config.CLUB_ID, "cafe_name": config.CAFE_NAME, "name": "현재카페"}]
            
            print(f"[INFO] 크롤링 대상 카페: {[c['name'] for c in multi_cafes]}")
            
            # 각 카페별로 키워드 검색
            for cafe_info in multi_cafes:
                if should_stop or check_stop_flag():
                    break
                
                current_club_id = cafe_info["club_id"]
                current_cafe_name = cafe_info["cafe_name"]
                cafe_display_name = cafe_info.get("name", current_cafe_name)
                
                print(f"\n{'='*50}")
                print(f"[카페] {cafe_display_name} (club_id: {current_club_id})")
                print(f"{'='*50}")
                
                # 전체글보기에서만 검색 (menu_id=0)
                for keyword in keywords:
                    if should_stop or check_stop_flag():
                        break
                        
                    try:
                        encoded = urllib.parse.quote(keyword)
                        search_url = f"https://cafe.naver.com/f-e/cafes/{current_club_id}/menus/0?viewType=L&ta=ARTICLE_COMMENT&page=1&q={encoded}"
                        
                        print(f"\n>>> [{cafe_display_name}] 키워드: '{keyword}'")
                        driver.get(search_url)
                        time.sleep(random.uniform(1, 2))  # 빠른 크롤링
                        
                        all_links = driver.find_elements(By.XPATH, "//a[contains(@href, '/articles/') and not(contains(@class, 'comment'))]")
                        
                        if not all_links: continue

                        target_links = []
                        for a_tag in all_links[:50]:  # 50개 글 탐색
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
                            
                            # 추가 중복 체크: visited_history.txt, comment_history.json, skip_links.json 모두 확인
                            if is_already_commented(link):
                                print(f" -> [Skip] 이미 처리한 글입니다. ({title[:10]}...)")
                                visited_links.add(link)
                                continue
                            
                            # ⚠️ 중요: 분석 전에 먼저 기록하여 Race Condition 방지
                            # 다른 키워드 검색에서 같은 글이 동시에 처리되는 것을 방지
                            append_history(link)
                            visited_links.add(link)
                            
                            try:
                                print(f"\n[분석] {title[:15]}...")
                                driver.get(link)
                                time.sleep(random.uniform(1, 2))  # 빠른 크롤링
                                
                                try: driver.switch_to.frame("cafe_main")
                                except: pass

                                # ⚠️ 중요: 내 댓글이 이미 있는지 확인 (크롤링 단계 체크)
                                if check_my_comment_exists(driver):
                                    print("  -> [PASS] 이미 내 댓글이 있는 글입니다.")
                                    driver.switch_to.default_content()
                                    continue
                                
                                # ⚠️ 날짜 체크: 2026년 2월 이후 글만 처리
                                if not check_post_date(driver, min_year=2026, min_month=2):
                                    driver.switch_to.default_content()
                                    continue

                                content = ""
                                try: content = driver.find_element(By.CSS_SELECTOR, "div.se-main-container").text
                                except:
                                    try: content = driver.find_element(By.CSS_SELECTOR, "div.ContentRenderer").text
                                    except: content = ""
                                
                                # 금지 키워드 체크
                                if contains_banned_keyword(title, content, banned_keywords):
                                    print(f"  -> [PASS] 금지 키워드 포함 글입니다.")
                                    driver.switch_to.default_content()
                                    continue
                                
                                # 댓글 목록도 함께 전달하여 AI가 더블체크할 수 있도록 함
                                existing_comments = ""
                                try:
                                    comment_elements = driver.find_elements(By.CSS_SELECTOR, "span.text_comment, div.comment_text")
                                    if comment_elements:
                                        existing_comments = "\n".join([c.text.strip()[:100] for c in comment_elements[:10]])
                                except:
                                    pass
                                
                                result = analyze_and_generate_reply(title, content, existing_comments=existing_comments)
                                
                                if result is None:
                                    print("  -> [PASS] (합격자/광고/무관함/이미 댓글 있음)")
                                    # 이미 위에서 기록했으므로 여기서는 기록하지 않음
                                    driver.switch_to.default_content()
                                    continue
                                
                                ai_reply, extra = result
                                print(f"  -> [작성] {ai_reply[:50]}...")

                                try:
                                    # 반자동 모드: 댓글을 실제로 달지 않고 pending 상태로 저장
                                    print("  -> [대기열 추가] 댓글 생성 완료 (승인 대기)")
                                    print(f"     생성된 댓글: {ai_reply[:100]}...")
                                    # 히스토리에 pending 상태로 저장 (visited_history는 이미 위에서 기록됨)
                                    save_comment_history(link, title, ai_reply, success=True, status="pending", **extra)

                                except Exception as e:
                                    print(f"  -> [실패] {e}")
                                    save_comment_history(link, title, ai_reply, success=False, status="pending", **extra)

                                driver.switch_to.default_content()

                            except Exception as e:
                                print(f"  -> [에러] {e}")
                                driver.switch_to.default_content()
                                time.sleep(2)

                    except Exception as e:
                        err_msg = str(e)
                        print(f"  -> [키워드 에러] {err_msg[:100]}")
                        # Chrome 크래시 감지 시 재시작
                        if "Connection refused" in err_msg or "invalid session" in err_msg.lower():
                            print("[경고] Chrome 크래시 감지! 브라우저 재시작...")
                            try:
                                driver.quit()
                            except:
                                pass
                            # 새 브라우저 시작
                            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
                            wait = WebDriverWait(driver, 10)
                            if not load_cookies(driver):
                                print("[에러] 재로그인 실패. 종료합니다.")
                                return
                            print("[복구] 브라우저 재시작 완료!")
            
            if should_stop:
                break
            
            # 크롤러 모드: 짧은 휴식 후 다음 사이클
            print(f">>> 휴식 {rest_minutes}분...")
            for _ in range(rest_minutes * 6):  # 10초 단위로 체크
                if should_stop or check_stop_flag():
                    break
                time.sleep(10)

    except KeyboardInterrupt:
        print("\n[크롤러] 사용자 중단")
    except Exception as e:
        print(f"\n[크롤러] 예외 발생: {e}")
    finally:
        print("[크롤러] 브라우저 종료 중...")
        driver.quit()
        
        # Headless 모드에서 user-data-dir 정리
        if HEADLESS_MODE:
            user_data_dir = os.path.join(SCRIPT_DIR, f"chrome_data_{os.getpid()}")
            if os.path.exists(user_data_dir):
                try:
                    import shutil
                    shutil.rmtree(user_data_dir)
                    print(f"[크롤러] Chrome user-data-dir 정리 완료: {user_data_dir}")
                except Exception as e:
                    print(f"[크롤러] Chrome user-data-dir 정리 실패: {e}")
        
        print("[크롤러] 종료 완료")


# ==========================================
# [게시 워커] - 승인된 댓글만 딜레이 적용하여 실제 게시
# ==========================================
POSTER_STOP_FLAG_FILE = os.path.join(SCRIPT_DIR, ".stop_poster")
poster_should_stop = False

def check_poster_stop_flag():
    """게시 워커 정지 플래그 파일 확인"""
    if os.path.exists(POSTER_STOP_FLAG_FILE):
        os.remove(POSTER_STOP_FLAG_FILE)
        return True
    return False

def load_approved_comments():
    """승인된 댓글 목록 로드"""
    if not os.path.exists(COMMENT_HISTORY_FILE):
        return []
    try:
        with open(COMMENT_HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
            return [c for c in history if c.get("status") == "approved"]
    except:
        return []

def update_comment_status(comment_id, new_status, posted_at=None, is_duplicate=False):
    """댓글 상태 업데이트"""
    if not os.path.exists(COMMENT_HISTORY_FILE):
        return False
    try:
        with open(COMMENT_HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        
        for comment in history:
            if comment.get("id") == comment_id:
                comment["status"] = new_status
                if posted_at:
                    comment["posted_at"] = posted_at
                if is_duplicate:
                    comment["is_duplicate"] = True
                # action_history에 추가
                if "action_history" not in comment:
                    comment["action_history"] = []
                comment["action_history"].append({
                    "action": new_status,
                    "timestamp": datetime.now().isoformat()
                })
                break
        
        with open(COMMENT_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[게시워커] 상태 업데이트 실패: {e}")
        return False

def run_poster_bot_with_restart():
    """게시 워커 자동 재시작 래퍼"""
    max_restart_count = 0  # 무제한 재시작
    restart_count = 0
    
    while True:
        try:
            print(f"\n[게시워커] 시작... (재시작 횟수: {restart_count})")
            run_poster_bot_once()
            print("[게시워커] 정상 종료")
            break  # 정상 종료시 루프 탈출
        except KeyboardInterrupt:
            print("\n[게시워커] 사용자에 의해 중단됨")
            break
        except Exception as e:
            restart_count += 1
            print(f"\n[게시워커] 오류 발생: {e}")
            print(f"[게시워커] 10초 후 자동 재시작... ({restart_count}번째)")
            
            if max_restart_count > 0 and restart_count >= max_restart_count:
                print(f"[게시워커] 최대 재시작 횟수({max_restart_count})에 도달. 종료합니다.")
                break
            
            time.sleep(10)  # 10초 대기 후 재시작
            continue

def run_poster_bot_once():
    """게시 워커: 승인된 댓글만 딜레이 적용하여 실제 게시 (단일 실행)"""
    global poster_should_stop
    poster_should_stop = False
    
    # 설정 로드
    bot_config = load_bot_config()
    min_delay_sec = bot_config.get("min_delay_seconds", 50)
    cph_min = bot_config.get("comments_per_hour_min", 5)
    cph_max = bot_config.get("comments_per_hour_max", 10)
    
    print(f"[게시워커] 시작 - 시간당 {cph_min}~{cph_max}개 댓글 게시")
    
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    if HEADLESS_MODE:
        print("[게시워커] Headless 모드로 실행")
        user_data_dir = os.path.join(SCRIPT_DIR, f"chrome_poster_{os.getpid()}")
        os.makedirs(user_data_dir, exist_ok=True)
        
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    else:
        chrome_options.add_argument("--start-maximized")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    wait = WebDriverWait(driver, 10)
    
    try:
        # 쿠키 기반 로그인
        if not load_cookies(driver):
            print("[게시워커] 로그인 실패. 종료합니다.")
            return
        
        print("[게시워커] 로그인 성공! 승인된 댓글 게시 시작...")
        
        while not poster_should_stop:
            if check_poster_stop_flag():
                print("[게시워커] 정지 플래그 감지, 종료합니다.")
                break
            
            # 승인된 댓글 로드
            approved_comments = load_approved_comments()
            
            if not approved_comments:
                print("[게시워커] 승인된 댓글 없음. 30초 후 재확인...")
                for _ in range(6):  # 5초 단위로 체크
                    if poster_should_stop or check_poster_stop_flag():
                        break
                    time.sleep(5)
                continue
            
            print(f"[게시워커] 승인된 댓글 {len(approved_comments)}개 발견")
            
            for comment in approved_comments:
                if poster_should_stop or check_poster_stop_flag():
                    break
                
                comment_id = comment.get("id")
                post_url = comment.get("post_url")
                ai_reply = comment.get("comment")
                title = comment.get("post_title", "")[:20]
                
                print(f"\n[게시] {title}... -> {post_url[:50]}...")
                
                try:
                    # URL 형식 변환: /f-e/cafes/... 형식을 기존 형식으로 변환
                    import re
                    converted_url = post_url
                    fe_match = re.search(r'/f-e/cafes/\d+/articles/(\d+)', post_url)
                    if fe_match:
                        article_id = fe_match.group(1)
                        # config에서 카페 이름 가져오기
                        converted_url = f"https://cafe.naver.com/{config.CAFE_NAME}/{article_id}"
                        print(f"  -> URL 변환: {converted_url}")
                    
                    driver.get(converted_url)
                    time.sleep(3)
                    
                    # iframe 전환
                    try:
                        driver.switch_to.frame("cafe_main")
                    except:
                        pass
                    
                    # ⚠️ 최종 중복 체크: 실제 게시 직전에 내 댓글이 있는지 확인
                    if check_my_comment_exists(driver):
                        print(f"  -> [Skip] 이미 내 댓글이 있음 - 게시완료(중복)로 처리")
                        update_comment_status(comment_id, "posted", posted_at=datetime.now().isoformat(), is_duplicate=True)
                        driver.switch_to.default_content()
                        continue
                    
                    # 댓글 입력 (이전 작동 코드와 동일)
                    inbox = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "comment_inbox")))
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", inbox)
                    inbox.click()
                    time.sleep(1)
                    
                    try:
                        driver.find_element(By.CLASS_NAME, "comment_inbox_text").send_keys(ai_reply)
                    except:
                        driver.switch_to.active_element.send_keys(ai_reply)
                    
                    time.sleep(1)
                    driver.find_element(By.XPATH, "//*[text()='등록']").click()
                    
                    # Alert 처리
                    try:
                        WebDriverWait(driver, 2).until(EC.alert_is_present())
                        driver.switch_to.alert.accept()
                        print(f"  -> [실패] Alert 발생")
                        update_comment_status(comment_id, "failed")
                        driver.switch_to.default_content()
                        continue
                    except:
                        pass
                    
                    print(f"  -> [게시 완료]")
                    update_comment_status(comment_id, "posted", posted_at=datetime.now().isoformat())
                    
                    driver.switch_to.default_content()
                    
                    # 딜레이 적용
                    bot_config = load_bot_config()
                    min_delay_sec = bot_config.get("min_delay_seconds", 50)
                    cph_min = bot_config.get("comments_per_hour_min", 5)
                    cph_max = bot_config.get("comments_per_hour_max", 10)
                    
                    if cph_min and cph_max and 0 < cph_min <= cph_max:
                        d_max = 3600 / cph_min
                        d_min_cand = 3600 / cph_max
                        d_min = max(min_delay_sec, d_min_cand)
                        d_min = min(d_min, d_max - 1) if d_min >= d_max else d_min
                        d_max = max(d_max, d_min + 1)
                    else:
                        d_min, d_max = min_delay_sec, 720
                    
                    delay = random.uniform(d_min, d_max)
                    print(f"  -> 다음 댓글까지 {delay:.0f}초 대기...")
                    
                    # 대기 중에도 종료 플래그 확인
                    for _ in range(int(delay / 5)):
                        if poster_should_stop or check_poster_stop_flag():
                            break
                        time.sleep(5)
                    
                except Exception as e:
                    print(f"  -> [에러] {type(e).__name__}: {str(e)[:200]}")
                    import traceback
                    traceback.print_exc()
                    update_comment_status(comment_id, "failed")
                    driver.switch_to.default_content()
                    time.sleep(2)
    
    except KeyboardInterrupt:
        print("\n[게시워커] 사용자 중단")
    except Exception as e:
        print(f"\n[게시워커] 예외 발생: {e}")
    finally:
        print("[게시워커] 브라우저 종료 중...")
        driver.quit()
        
        if HEADLESS_MODE:
            user_data_dir = os.path.join(SCRIPT_DIR, f"chrome_poster_{os.getpid()}")
            if os.path.exists(user_data_dir):
                try:
                    import shutil
                    shutil.rmtree(user_data_dir)
                except:
                    pass
        
        print("[게시워커] 종료 완료")

def run_poster_bot():
    """게시 워커 - 무한 루프로 계속 실행 (정상 종료 시에도 재시작)"""
    restart_count = 0
    
    while True:
        try:
            print(f"\n{'='*60}")
            print(f"[게시워커] 시작... (재시작 횟수: {restart_count})")
            print(f"{'='*60}")
            run_poster_bot_once()
            # 정상 종료 시에도 재시작 (break 제거)
            print("[게시워커] 사이클 완료, 10초 후 재시작...")
            time.sleep(10)
            restart_count += 1
        except KeyboardInterrupt:
            print("\n[게시워커] 사용자에 의해 중단됨")
            break
        except Exception as e:
            restart_count += 1
            print(f"\n{'='*60}")
            print(f"[게시워커] 오류 발생: {type(e).__name__}: {str(e)[:200]}")
            print(f"[게시워커] 10초 후 자동 재시작... ({restart_count}번째)")
            print(f"{'='*60}")
            time.sleep(10)
            continue

if __name__ == "__main__":
    # 봇 시작
    print("[초기화] 학습 데이터 실시간 로드 방식으로 실행")
    print("  - Answer Agent: 좋은 예시(게시완료/승인됨) 10개 + 나쁜 예시(취소됨) 10개")
    print("  - Query Agent: 부적절한 글 예시 20개")
    
    run_search_bot()