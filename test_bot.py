import time
import os
import platform
import pyperclip
import google.generativeai as genai
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

# ================= [테스트 설정 구역] =================
NAVER_ID = "horse324"   
NAVER_PW = "1qaz2wsx" 
GEMINI_API_KEY = "AIzaSyDfB7KbYJAKlDbcdythNT6WWG3txKrPz44"
TARGET_URL = "https://cafe.naver.com/f-e/cafes/10197921/articles/29392388"
HISTORY_FILE = "visited_history.txt"
# ====================================================

# ★ 최신 Gemini 2.5 Flash 모델 적용 (2026년 1월 기준 무료 티어 최신)
genai.configure(api_key=GEMINI_API_KEY)

# 최신 모델: gemini-2.5-flash (무료 티어에서 사용 가능한 최신 버전)
try:
    model = genai.GenerativeModel('gemini-2.5-flash')
    print("[INFO] Gemini 2.5 Flash 모델을 사용합니다.")
except Exception as e:
    print(f"[WARN] 2.5-flash 모델 로드 실패, fallback 시도 중... ({e})")
    model = genai.GenerativeModel('gemini-2.0-flash')

def get_ctrl_key():
    return Keys.COMMAND if platform.system() == 'Darwin' else Keys.CONTROL

def clipboard_input(driver, user_input):
    pyperclip.copy(user_input)
    ctrl_key = get_ctrl_key()
    ActionChains(driver).key_down(ctrl_key).send_keys('v').key_up(ctrl_key).perform()
    time.sleep(1)

# [기능 2] 중복 방지
def check_history_system(link):
    print("\n" + "="*40)
    print(" >>> [점검 2] 중복 방지 시스템 테스트")
    print("="*40)
    
    file_path = os.path.abspath(HISTORY_FILE)
    print(f"📁 장부 파일 위치: {file_path}")
    
    visited = set()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            visited = set(line.strip() for line in f.readlines())
        print(f"📖 현재 장부에 기록된 글 개수: {len(visited)}개")
    else:
        print("📖 장부 파일이 없습니다. (새로 생성 예정)")

    if link in visited:
        print(f"⚠️ 결과: [이미 방문한 글]입니다. (중복 방지 작동 중)")
    else:
        print(f"✅ 결과: [처음 보는 글]입니다. (작업 대상)")
        try:
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(link + "\n")
            print("💾 장부에 현재 링크를 [저장]했습니다.")
        except Exception as e:
            print(f"❌ 저장 실패: {e}")

# [기능 3] AI 댓글 생성 (Gemini 3.0)
def test_ai_generation(title, content):
    print("\n" + "="*40)
    print(" >>> [점검 3] AI 댓글 생성 테스트 (Gemini 3.0 Pro)")
    print("="*40)
    
    try:
        print("🤖 Gemini 3.0에게 작성을 요청하는 중...")
        prompt = f"""
        너는 수만휘 카페의 친절한 서울대 기계공학부 선배야.
        후배의 글을 보고 공감해주고 조언해주는 댓글을 1개 써줘.
        
        [글 제목]: {title}
        [글 본문]: {content[:800]}
        
        조건: 해요체 사용, 2문장 이내, 광고 티 내지 말 것.
        """
        response = model.generate_content(prompt)
        reply = response.text.strip()
        
        print(f"💬 [생성된 댓글]\n--------------------------------\n{reply}\n--------------------------------")
        print("✅ AI 기능 정상 작동 확인 완료.")
        return reply
    except Exception as e:
        print(f"❌ AI 생성 실패: {e}")
        # 3.0 모델이 최신이라 라이브러리 업데이트가 필수일 수 있습니다.
        print("👉 팁: 터미널에 'pip install --upgrade google-generativeai' 꼭 실행하세요.")
        return None

def run_test():
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    try:
        print("🚀 [기능 점검 시작] 브라우저를 엽니다...")
        
        # 1. 로그인
        driver.get("https://nid.naver.com/nidlogin.login")
        time.sleep(2)
        driver.find_element(By.ID, "id").click()
        clipboard_input(driver, NAVER_ID)
        time.sleep(1)
        driver.find_element(By.ID, "pw").click()
        clipboard_input(driver, NAVER_PW)
        time.sleep(1)
        driver.find_element(By.ID, "log.login").click()
        print(">>> 로그인 대기 (15초)... 2차 인증 필요시 직접 하세요.")
        time.sleep(15)

        # 2. 타겟 글 진입
        print(f">>> 테스트 글 진입: {TARGET_URL}")
        driver.get(TARGET_URL)
        time.sleep(3)
        
        try:
            driver.switch_to.frame("cafe_main")
        except:
            print("❌ cafe_main 프레임 진입 실패")

        # [점검 1] 본문 추출
        print("\n" + "="*40)
        print(" >>> [점검 1] 본문 추출 테스트")
        print("="*40)
        
        try:
            title_elem = driver.find_element(By.CSS_SELECTOR, "h3.title_text")
            extracted_title = title_elem.text
            print(f"📌 [제목]: {extracted_title}")
        except:
            extracted_title = "제목 없음"

        try:
            content_elem = driver.find_element(By.CSS_SELECTOR, "div.se-main-container")
            extracted_content = content_elem.text
        except:
            try:
                content_elem = driver.find_element(By.CSS_SELECTOR, "div.ContentRenderer")
                extracted_content = content_elem.text
            except:
                extracted_content = "본문 없음"
        
        print(f"📝 [본문]: {extracted_content[:100]}...")

        # [점검 2] 중복 방지
        check_history_system(TARGET_URL)

        # [점검 3] AI 생성 (3.0 Pro)
        test_ai_generation(extracted_title, extracted_content)

        print("\n✅ 테스트 완료. (60초 후 종료)")
        time.sleep(60)

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_test()