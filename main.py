import time
import random
import platform
import pyperclip
import urllib.parse 
import os 
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
# [설정] AI 모델 및 API 키
# ==========================================
HISTORY_FILE = "visited_history.txt"

# config.py에서 API 키 가져오기
genai.configure(api_key=config.GEMINI_API_KEY)
try:
    model = genai.GenerativeModel('gemini-2.5-flash')
    print("[INFO] Gemini 2.5 Flash 모델 가동")
except:
    model = genai.GenerativeModel('gemini-2.0-flash')

TARGET_KEYWORDS = [
    "생기부", "세특", "면접", "서울대", "기계", 
    "공대", "ai", "인공지능", "학종", "수시", 
    "자소서", "공학", "컴공"
]

# ==========================================
# [핵심] 깐깐한 AI 판독기 (합격자/광고 컷)
# ==========================================
def analyze_and_generate_reply(title, content):
    try:
        usps = [
            "서울대 기계 21학번입니다.",
            "저도 내신 1.4로 서울대 뚫었는데,",
            "지금 AI 법인 운영하면서 보니까,",
            "입시 컨설팅 꽤 오래 해봤는데,"
        ]
        selected_usp = random.choice(usps)
        
        prompt = f"""
        당신은 수만휘의 서울대 기계공학부 선배입니다.
        게시글을 분석하여 **'도움이 필요한 수험생'**에게만 댓글을 다세요.

        [게시글 정보]
        제목: {title}
        본문: {content[:1000]}

        [🚨 1차 필터 - 무조건 PASS 해야 하는 경우]
        다음 중 하나라도 해당되면 내용 보지 말고 무조건 "PASS" 출력하세요.
        1. **이미 합격한 사람:** "합격 후기", "최초합", "합격했습니다", "대학 갑니다" 등 자랑/후기글.
        2. **정보 공유/자료 배포:** 질문이 아니라 팁을 알려주는 글, 자료 나눔글.
        3. **광고/홍보:** 학원 홍보, 과외 모집, 스터디 모집.
        4. **공지사항:** 카페 공지, 필독 등.
        5. **단순 잡담:** 연애, 유머, 입시와 무관한 일상.

        [✅ 2차 타겟 - 댓글 달아야 하는 경우]
        - 생기부, 세특, 자소서 방향성을 고민하는 학생
        - 자신의 스펙(내신 등)을 올리고 합불 가능성을 묻는 학생
        - 멘탈이 흔들려 조언이 필요한 학생
        
        [작성 규칙]
        1. **목적:** 수시/학종/생기부의 중요성 강조. (정시 추천 금지)
        2. **길이:** 3문장 이내. 짧고 담백하게.
        3. **말투:** "~해요"체 사용. (따옴표 사용 금지)
        4. **필수 포함:** "{selected_usp}" 멘트 삽입.
        5. **행동 유도:** "부족한 부분 쪽지 주시면 봐드릴게요"로 마무리.

        [출력]
        PASS 또는 댓글 내용
        """
        
        response = model.generate_content(prompt)
        result = response.text.strip()
        result = result.replace('"', '').replace("'", "") # 따옴표 제거

        if "PASS" in result:
            return None
        else:
            return result
            
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

def copy_input(driver, xpath, text):
    pyperclip.copy(text)
    driver.find_element(By.XPATH, xpath).click()
    cmd_key = Keys.COMMAND if platform.system() == 'Darwin' else Keys.CONTROL
    ActionChains(driver).key_down(cmd_key).send_keys('v').key_up(cmd_key).perform()
    time.sleep(1)

# ==========================================
# [메인 로봇]
# ==========================================
def run_search_bot():
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument("--start-maximized") 
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    wait = WebDriverWait(driver, 10) 

    try:
        print("========== [타겟 정밀 타격 봇 (필터 강화)] ==========")
        visited_links = load_history()
        
        driver.get("https://nid.naver.com/nidlogin.login")
        time.sleep(random.uniform(2, 3))
        copy_input(driver, '//*[@id="id"]', config.NAVER_ID)
        copy_input(driver, '//*[@id="pw"]', config.NAVER_PW)
        driver.find_element(By.ID, "log.login").click()
        print(">>> 로그인 대기 (15초)...")
        time.sleep(15) 

        while True:
            for keyword in TARGET_KEYWORDS:
                try:
                    encoded = urllib.parse.quote(keyword)
                    search_url = f"https://cafe.naver.com/f-e/cafes/{config.CLUB_ID}/menus/0?viewType=L&ta=ARTICLE_COMMENT&page=1&q={encoded}"
                    
                    print(f"\n>>> 키워드: '{keyword}'")
                    driver.get(search_url)
                    time.sleep(random.uniform(3, 4))
                    
                    all_links = driver.find_elements(By.XPATH, "//a[contains(@href, '/articles/') and not(contains(@class, 'comment'))]")
                    
                    if not all_links: continue

                    target_links = []
                    # 상위 8개만 긁되, 중복 제거 로직은 루프 안에서 처리
                    for a_tag in all_links[:8]:
                        try:
                            raw_link = a_tag.get_attribute('href')
                            clean_link = raw_link.split('?')[0] if '?' in raw_link else raw_link
                            title = a_tag.text.strip()
                            # 목록 생성 단계에서는 일단 다 담습니다 (나중에 거름)
                            if len(title) > 1: 
                                target_links.append((clean_link, title))
                        except: continue
                    
                    # 여기서 중복 제거된 진짜 개수를 확인하는 게 좋지만, 로직 간소화를 위해 아래 루프에서 처리
                    print(f" -> 대상(중복포함): {len(target_links)}개")

                    for link, title in target_links:
                        # ★★★ [핵심 수정] 진입 직전 '더블 체크' ★★★
                        # 목록을 만들 때는 없었어도, 바로 앞 순서에서 처리해서 visited_links에 들어갔을 수 있음.
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
                                
                            print(f"  -> [작성] {ai_reply}")

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
                                    continue
                                except: pass

                                print("  -> [완료]")
                                append_history(link)
                                visited_links.add(link)
                                
                                time.sleep(random.uniform(50, 80))

                            except Exception as e:
                                print(f"  -> [실패] {e}")

                            driver.switch_to.default_content()

                        except:
                            driver.switch_to.default_content()
                            time.sleep(2)

                except: pass
            
            print(">>> 휴식 3분...")
            time.sleep(180)

    except KeyboardInterrupt:
        print("\n종료")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_search_bot()