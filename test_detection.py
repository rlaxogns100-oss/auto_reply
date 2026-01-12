import time
import pyperclip
import os 
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
import config

# ==========================================
# [진단용 설정] 테스트할 글 URL 하나만 딱 넣으세요.
# 아까 실패했던 그 글의 링크를 넣으시면 제일 좋습니다.
TEST_TARGET_URL = "https://cafe.naver.com/f-e/cafes/10197921/articles/29392388" 
# ==========================================

def clipboard_input(driver, user_input):
    pyperclip.copy(user_input)
    # 맥/윈도우 호환
    ctrl_key = Keys.COMMAND if 'Darwin' in os.uname().sysname else Keys.CONTROL
    ActionChains(driver).key_down(ctrl_key).send_keys('v').key_up(ctrl_key).perform()
    time.sleep(1)

def run_diagnosis():
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized") 
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    try:
        print("========== [🔍 감지 능력 정밀 진단] ==========")
        
        # 1. 로그인 (로그인해야 댓글창이 보임)
        print("1. 로그인 시도...")
        driver.get("https://nid.naver.com/nidlogin.login")
        time.sleep(2)
        driver.find_element(By.ID, "id").click()
        clipboard_input(driver, config.NAVER_ID)
        time.sleep(1)
        driver.find_element(By.ID, "pw").click()
        clipboard_input(driver, config.NAVER_PW)
        time.sleep(1)
        driver.find_element(By.ID, "log.login").click()
        
        print(">>> 2차 인증 등 대기 (20초)... 로그인 확실히 해주세요.")
        time.sleep(20)

        # 2. 타겟 글 진입
        print(f"\n2. 타겟 글 진입: {TEST_TARGET_URL}")
        driver.get(TEST_TARGET_URL)
        time.sleep(5) # 충분히 로딩 대기

        # 3. [핵심] Iframe 확인
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"\n3. 화면 내 iframe 개수: {len(iframes)}개")
        for i, frame in enumerate(iframes):
            print(f"   - iframe {i}: name='{frame.get_attribute('name')}', id='{frame.get_attribute('id')}'")

        # 4. [진단 A] 그냥 겉에서 제목 찾아보기
        print("\n4. [진단 A] 메인 프레임에서 제목 탐색 시도...")
        try:
            title = driver.find_element(By.CSS_SELECTOR, "h3.title_text").text
            print(f"   >>> 성공! 제목 감지됨: {title}")
        except:
            print("   >>> 실패. (제목 태그 h3.title_text 없음)")

        # 5. [진단 B] 'cafe_main' iframe으로 스위칭 후 찾아보기
        print("\n5. [진단 B] 'cafe_main' iframe 스위칭 시도...")
        try:
            driver.switch_to.frame("cafe_main")
            print("   >>> 스위칭 성공! 내부 요소 탐색 시작...")
            
            try:
                # iframe 안에서 제목 찾기
                title = driver.find_element(By.CSS_SELECTOR, "h3.title_text").text
                print(f"   >>> [IFRAME 내부] 제목 감지됨: {title}")
            except:
                print("   >>> [IFRAME 내부] 제목 감지 실패.")

            try:
                # iframe 안에서 댓글창 찾기
                box = driver.find_element(By.CLASS_NAME, "comment_inbox")
                print(f"   >>> [IFRAME 내부] 댓글창 박스 감지됨!")
            except:
                print("   >>> [IFRAME 내부] 댓글창 감지 실패.")
                
        except:
            print("   >>> 'cafe_main' iframe이 없어서 스위칭 불가.")

        # 6. HTML 덤프 (이게 제일 중요합니다)
        print("\n6. 현재 로봇이 보고 있는 화면 소스를 파일로 저장합니다...")
        with open("debug_page_source.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("   >>> 'debug_page_source.html' 저장 완료. 이 파일을 확인하면 원인을 100% 알 수 있습니다.")

    except Exception as e:
        print(f"에러 발생: {e}")
    finally:
        # 창 닫지 않고 유지 (직접 눈으로 확인하라고)
        print("\n>>> 진단 종료. 브라우저는 닫지 않습니다.")
        # driver.quit() 

if __name__ == "__main__":
    run_diagnosis()