import time
import random
import platform
import pyperclip
import urllib.parse 
import os 
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

# [영구 기억 장치]
HISTORY_FILE = "visited_history.txt"

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
    except Exception as e:
        print(f" -> [경고] 장부 기록 실패: {e}")

# [메인 로봇]
def run_search_bot():
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument("--start-maximized") 
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    wait = WebDriverWait(driver, 10) 

    try:
        print("========== [입력 강화형 봇 가동] ==========")
        visited_links = load_history()
        print(f">>> 과거 기록 {len(visited_links)}개 로드 완료.")
        
        # 1. 로그인 (기존 코드 유지)
        driver.get("https://nid.naver.com/nidlogin.login")
        time.sleep(random.uniform(2, 3))
        
        # 맥용 클립보드 복사 함수 (로그인용)
        def copy_input(xpath, text):
            pyperclip.copy(text)
            driver.find_element(By.XPATH, xpath).click()
            # 맥은 COMMAND, 윈도우는 CONTROL
            cmd_key = Keys.COMMAND if platform.system() == 'Darwin' else Keys.CONTROL
            ActionChains(driver).key_down(cmd_key).send_keys('v').key_up(cmd_key).perform()
            time.sleep(1)

        copy_input('//*[@id="id"]', config.NAVER_ID)
        copy_input('//*[@id="pw"]', config.NAVER_PW)
        driver.find_element(By.ID, "log.login").click()
        print(">>> 로그인 대기 (15초)...")
        time.sleep(15) 

        while True:
            for keyword in config.SEARCH_KEYWORDS:
                try:
                    # 검색
                    encoded = urllib.parse.quote(keyword)
                    search_url = f"https://cafe.naver.com/f-e/cafes/{config.CLUB_ID}/menus/0?viewType=L&ta=ARTICLE_COMMENT&page=1&q={encoded}"
                    
                    print(f"\n>>> 검색: '{keyword}'")
                    driver.get(search_url)
                    time.sleep(random.uniform(3, 4))
                    
                    all_links = driver.find_elements(By.XPATH, "//a[contains(@href, '/articles/') and not(contains(@class, 'comment'))]")
                    
                    if not all_links:
                        print(" -> 검색 결과 없음")
                        continue

                    target_links = []
                    for a_tag in all_links[:10]:
                        try:
                            raw_link = a_tag.get_attribute('href')
                            clean_link = raw_link.split('?')[0] if '?' in raw_link else raw_link
                            title = a_tag.text.strip()
                            if len(title) > 1 and clean_link not in visited_links:
                                target_links.append((clean_link, title))
                        except: continue
                    
                    print(f" -> 작업 대상: {len(target_links)}개")

                    for link, title in target_links:
                        try:
                            print(f"\n[진입] {title[:10]}...")
                            driver.get(link)
                            time.sleep(random.uniform(2, 3))
                            
                            # 1. Iframe 진입
                            try:
                                driver.switch_to.frame("cafe_main")
                            except: pass # 없으면 그냥 진행

                            try:
                                # 2. 댓글 박스 찾기 (스크린샷 족보: comment_inbox)
                                inbox_box = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "comment_inbox")))
                                
                                # 3. 스크롤 & 클릭
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", inbox_box)
                                time.sleep(1)
                                inbox_box.click()
                                time.sleep(1.5) # 클릭 후 커서 잡힐 때까지 충분히 대기
                                
                                # 4. ★ [핵심 변경] 클립보드 대신 직접 타이핑 (send_keys)
                                # 박스를 클릭했으므로 '현재 포커스된 요소(textarea)'에 글자를 보냅니다.
                                msg = random.choice(config.REPLY_MESSAGES)
                                
                                # 텍스트 입력창(textarea)을 직접 찾아서 꽂아넣음 (더 확실함)
                                try:
                                    text_area = driver.find_element(By.CLASS_NAME, "comment_inbox_text")
                                    text_area.send_keys(msg)
                                except:
                                    # 못 찾으면 그냥 활성 요소에 입력
                                    driver.switch_to.active_element.send_keys(msg)
                                
                                time.sleep(1) # 입력 후 대기
                                
                                # 5. 등록 버튼 클릭
                                submit_btn = driver.find_element(By.XPATH, "//*[text()='등록']")
                                submit_btn.click()
                                
                                # 6. ★ [팝업 처리] "내용을 입력해주세요" 뜨면 닫고 실패 처리
                                try:
                                    # 2초 동안 팝업(Alert)이 뜨는지 감시
                                    WebDriverWait(driver, 2).until(EC.alert_is_present())
                                    alert = driver.switch_to.alert
                                    print(f"  -> [실패] 팝업 발생: {alert.text}")
                                    alert.accept() # 확인 버튼 눌러서 닫기
                                    continue # 다음 글 진행
                                except:
                                    # 팝업 안 떴으면 성공
                                    pass

                                print(f"  -> [완료] 댓글 작성 성공!")
                                append_history(link)
                                visited_links.add(link)
                                
                                wait_time = random.uniform(40, 70)
                                print(f"  -> 대기: {int(wait_time)}초")
                                time.sleep(wait_time)

                            except Exception as e:
                                print(f"  -> [실패] 댓글 작성 중 에러: {e}")
                                continue

                            driver.switch_to.default_content()

                        except Exception as e:
                            print(f" -> 글 진입 실패: {e}")
                            driver.switch_to.default_content()
                            time.sleep(2)

                except Exception as e:
                    print(f"오류: {e}")
            
            print(">>> 전체 순회 완료. 1분 휴식...")
            time.sleep(60)

    except KeyboardInterrupt:
        print("\n종료")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_search_bot()