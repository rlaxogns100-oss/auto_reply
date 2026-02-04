import time
import json
import os
import sys
import subprocess
import signal
import psutil
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from selenium.webdriver.common.proxy import Proxy, ProxyType
from importlib import reload
import config


def log(msg):
    """즉시 출력되는 로그 함수"""
    print(msg, flush=True)


class TorManager:
    """Tor 프로세스 관리 및 IP 변경"""
    
    def __init__(self):
        self.tor_process = None
        self.last_ip_change = 0
        self.tor_pid = None
        
    def start_tor(self):
        """Tor 프로세스 시작"""
        if not config.USE_TOR:
            return True
            
        try:
            # 기존 Tor 프로세스 종료 (자신의 프로세스만)
            self.stop_tor()
            
            log("Tor 프로세스 시작 중...")
            
            # Tor를 백그라운드에서 실행
            self.tor_process = subprocess.Popen(
                ['/opt/homebrew/opt/tor/bin/tor'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid  # 새로운 세션 생성
            )
            
            self.tor_pid = self.tor_process.pid
            
            # Tor가 준비될 때까지 대기
            time.sleep(15)  # 15초로 증가
            log(f"Tor 프로세스 시작 완료 (PID: {self.tor_pid})")
            self.last_ip_change = time.time()
            return True
            
        except Exception as e:
            log(f"Tor 시작 실패: {e}")
            return False
    
    def stop_tor(self):
        """Tor 프로세스 종료 (자신의 프로세스만)"""
        if self.tor_process:
            try:
                log(f"Tor 프로세스 종료 중... (PID: {self.tor_pid})")
                # 프로세스 그룹 전체 종료
                os.killpg(os.getpgid(self.tor_process.pid), signal.SIGTERM)
                self.tor_process.wait(timeout=3)
                log("Tor 프로세스 종료 완료")
            except Exception as e:
                try:
                    # 강제 종료
                    os.killpg(os.getpgid(self.tor_process.pid), signal.SIGKILL)
                except:
                    pass
            self.tor_process = None
            self.tor_pid = None
    
    def renew_ip(self):
        """새로운 IP로 변경 (Tor 재시작)"""
        if not config.USE_TOR:
            return True
            
        log("\n" + "="*50)
        log("IP 변경 중... (Tor 재시작)")
        log("="*50)
        
        self.stop_tor()
        time.sleep(2)
        result = self.start_tor()
        
        if result:
            log("새로운 IP로 변경 완료!")
        
        return result
    
    def should_renew_ip(self):
        """IP 변경이 필요한지 확인 (댓글 개수 기반)"""
        if not config.USE_TOR:
            return False
        # 시간 기반 대신 댓글 개수 기반으로 변경
        return False  # run()에서 직접 체크


class DCInsideCrawler:
    def __init__(self):
        self.driver = None
        self.commented_links = self.load_commented_links()  # 링크 기반으로 변경
        self.base_url = "https://gall.dcinside.com"
        self.tor_manager = TorManager()
        self.comment_count = 0
        
    def setup_driver(self):
        """Chrome 드라이버 설정"""
        log("Chrome 드라이버 초기화 중...")
        
        chrome_options = Options()
        
        # Headless 모드 설정 (창 안 보이게)
        if config.HEADLESS:
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--no-first-run')
            chrome_options.add_argument('--no-default-browser-check')
            log("Headless 모드 활성화")
        
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('--disable-infobars')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-popup-blocking')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # Tor 프록시 설정
        if config.USE_TOR:
            chrome_options.add_argument(f'--proxy-server=socks5://127.0.0.1:{config.TOR_SOCKS_PORT}')
            log(f"Tor 프록시 설정: socks5://127.0.0.1:{config.TOR_SOCKS_PORT}")
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            '''
        })
        self.driver.implicitly_wait(5)
        log("Chrome 드라이버 초기화 완료")
    
    def restart_with_new_ip(self):
        """새 IP로 변경 (브라우저 유지, Tor만 재시작)"""
        log("\nIP 변경 중...")
        
        # Tor IP 변경
        if not self.tor_manager.renew_ip():
            log("IP 변경 실패!")
            return False
        
        self.comment_count = 0
        return True
        
    def load_commented_links(self):
        """이미 댓글 단 링크 목록 로드"""
        filepath = os.path.join(os.path.dirname(__file__), 'commented_links.json')
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                return json.load(f)
        return []
    
    def save_commented_links(self):
        """댓글 단 링크 목록 저장 (최근 100개만 유지)"""
        filepath = os.path.join(os.path.dirname(__file__), 'commented_links.json')
        with open(filepath, 'w') as f:
            json.dump(self.commented_links[-100:], f)
    
    def extract_post_number(self, link):
        """URL에서 게시글 번호 추출 (no= 파라미터)"""
        match = re.search(r'[?&]no=(\d+)', link)
        if match:
            return match.group(1)
        return None
    
    def is_already_commented(self, link):
        """이미 댓글을 달았는지 확인 (게시글 번호로 비교)"""
        post_no = self.extract_post_number(link)
        if not post_no:
            return False
        
        # 저장된 링크들의 게시글 번호 추출
        for commented_link in self.commented_links:
            commented_no = self.extract_post_number(commented_link)
            if commented_no == post_no:
                return True
        return False
    
    def is_driver_alive(self):
        """드라이버가 살아있는지 확인"""
        try:
            self.driver.current_url
            return True
        except:
            return False
    
    def restart_driver(self):
        """드라이버 재시작"""
        log("\n⚠️ 드라이버 재시작 중...")
        try:
            if self.driver:
                self.driver.quit()
        except:
            pass
        
        # chromedriver 프로세스 정리
        try:
            import subprocess
            subprocess.run(['pkill', '-9', '-f', 'chromedriver'], capture_output=True)
            time.sleep(2)
        except:
            pass
        
        self.setup_driver()
        log("✓ 드라이버 재시작 완료!")
    
    def get_latest_posts(self, gallery_url):
        """최신 게시글 목록 가져오기 (공지글 제외)"""
        try:
            # 드라이버 상태 확인
            if not self.is_driver_alive():
                log("⚠️ 드라이버가 죽어있음! 재시작...")
                self.restart_driver()
            
            log(f"갤러리 접속 중: {gallery_url}")
            self.driver.set_page_load_timeout(120)  # 2분으로 증가
            try:
                self.driver.get(gallery_url)
            except Exception as e:
                log(f"갤러리 로딩 타임아웃: {e}")
                # 타임아웃 시 드라이버 재시작
                self.restart_driver()
                return []
            time.sleep(2)  # 대기 시간 단축
            
            posts = []
            
            # 게시글 목록 테이블에서 tr 요소들 가져오기
            post_rows = self.driver.find_elements(By.CSS_SELECTOR, "tr.ub-content")
            
            log(f"발견된 게시글 행: {len(post_rows)}개")
            
            for row in post_rows:
                try:
                    # 게시글 번호
                    num_elem = row.find_element(By.CSS_SELECTOR, "td.gall_num")
                    post_num = num_elem.text.strip()
                    
                    # 공지, 설문, AD 등은 건너뛰기
                    if not post_num.isdigit():
                        continue
                    
                    # 제목과 링크
                    title_elem = row.find_element(By.CSS_SELECTOR, "td.gall_tit a:first-child")
                    title = title_elem.text.strip()
                    link = title_elem.get_attribute("href")
                    
                    if link and not link.startswith("http"):
                        link = self.base_url + link
                    
                    posts.append({
                        'num': post_num,
                        'title': title,
                        'link': link
                    })
                    
                except Exception as e:
                    continue
            
            log(f"총 {len(posts)}개의 일반 게시글 발견")
            return posts[:10]  # 최신 10개만 반환
            
        except Exception as e:
            log(f"게시글 목록 가져오기 실패: {e}")
            import traceback
            traceback.print_exc()
            # 연결 에러면 드라이버 재시작
            if "Connection refused" in str(e) or "MaxRetryError" in str(e):
                self.restart_driver()
            return []
    
    def close_popups(self):
        """팝업 닫기"""
        try:
            try:
                alert = self.driver.switch_to.alert
                alert.dismiss()
            except:
                pass
            
            close_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".btn_cancel, .close, .layer_close")
            for btn in close_buttons:
                try:
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(0.5)
                except:
                    pass
        except:
            pass
    
    def write_comment(self, post_url, post_num):
        """게시글에 댓글 작성"""
        try:
            # 드라이버 상태 확인
            if not self.is_driver_alive():
                log("⚠️ 드라이버가 죽어있음! 재시작...")
                self.restart_driver()
            
            log(f"게시글 접속 중: {post_url}")
            self.driver.set_page_load_timeout(60)  # 1분 타임아웃
            try:
                self.driver.get(post_url)
            except Exception as e:
                log(f"  페이지 로딩 타임아웃 또는 오류: {e}")
                if "Connection refused" in str(e) or "MaxRetryError" in str(e):
                    self.restart_driver()
                return False
            time.sleep(2)  # 대기 시간 단축
            
            self.close_popups()
            
            # 댓글 영역으로 스크롤
            try:
                comment_area = self.driver.find_element(By.CSS_SELECTOR, ".comment_write, .cmt_write_box")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", comment_area)
                time.sleep(1)
            except:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.7);")
                time.sleep(1)
            
            # 비회원 닉네임 입력
            try:
                name_selectors = ["input#name", "input[name='name']", ".cmt_nickname input", "input.cmt_name"]
                for selector in name_selectors:
                    try:
                        name_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if name_input.is_displayed():
                            name_input.clear()
                            name_input.send_keys(config.NICKNAME)
                            log(f"  닉네임 입력: {config.NICKNAME}")
                            break
                    except:
                        continue
            except Exception as e:
                log(f"  닉네임 입력 실패")
            
            # 비회원 비밀번호 입력
            try:
                pw_selectors = ["input#password", "input[name='password']", ".cmt_password input", "input.cmt_pw"]
                for selector in pw_selectors:
                    try:
                        pw_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if pw_input.is_displayed():
                            pw_input.clear()
                            pw_input.send_keys(config.PASSWORD)
                            log("  비밀번호 입력 완료")
                            break
                    except:
                        continue
            except Exception as e:
                log(f"  비밀번호 입력 실패")
            
            # 댓글 입력창의 label을 먼저 클릭
            try:
                label = self.driver.find_element(By.CSS_SELECTOR, "label.cmt_textarea_label")
                if label.is_displayed():
                    self.driver.execute_script("arguments[0].click();", label)
                    log("  댓글 입력창 label 클릭")
                    time.sleep(0.5)
            except:
                pass
            
            # 댓글 입력창 찾기
            comment_box = None
            
            try:
                comment_box = self.driver.find_element(By.CSS_SELECTOR, f"textarea#memo_{post_num}")
                log(f"  댓글 입력창 발견: textarea#memo_{post_num}")
            except:
                pass
            
            if not comment_box:
                selectors = [
                    "textarea[id^='memo_']",
                    "textarea.cmt_textarea",
                    ".comment_write textarea",
                    ".cmt_write_box textarea"
                ]
                for selector in selectors:
                    try:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for elem in elements:
                            if elem.is_displayed():
                                comment_box = elem
                                log(f"  댓글 입력창 발견: {selector}")
                                break
                        if comment_box:
                            break
                    except:
                        continue
            
            if not comment_box:
                log("  ✗ 댓글 입력창을 찾을 수 없습니다.")
                return False
            
            # JavaScript로 댓글 입력
            self.driver.execute_script("""
                arguments[0].focus();
                arguments[0].value = arguments[1];
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            """, comment_box, config.COMMENT_TEXT)
            log(f"  댓글 입력: {config.COMMENT_TEXT}")
            time.sleep(1)
            
            # 등록 버튼 찾기
            submit_btn = None
            
            btn_selectors = [
                "button.btn_cmt",
                "button.btn_blue",
                ".cmt_write_box button",
                ".comment_write button"
            ]
            
            for selector in btn_selectors:
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for btn in buttons:
                        if btn.is_displayed():
                            btn_text = btn.text.strip()
                            if "등록" in btn_text:
                                submit_btn = btn
                                log(f"  등록 버튼 발견: {selector}")
                                break
                    if submit_btn:
                        break
                except:
                    continue
            
            if not submit_btn:
                try:
                    buttons = self.driver.find_elements(By.TAG_NAME, "button")
                    for btn in buttons:
                        if btn.is_displayed() and "등록" in btn.text:
                            submit_btn = btn
                            log("  등록 버튼 발견")
                            break
                except:
                    pass
            
            if not submit_btn:
                log("  ✗ 등록 버튼을 찾을 수 없습니다.")
                return False
            
            # 버튼 클릭
            self.driver.execute_script("arguments[0].click();", submit_btn)
            log("  등록 버튼 클릭 완료")
            time.sleep(2)
            
            # 알림창 처리 (타임아웃 증가)
            try:
                alert = WebDriverWait(self.driver, 10).until(EC.alert_is_present())
                alert_text = alert.text
                log(f"  알림: {alert_text}")
                alert.accept()
                time.sleep(1)
                
                if "등록" in alert_text or "완료" in alert_text or "정상" in alert_text:
                    self.comment_count += 1
                    log(f"  댓글 카운트 증가: {self.comment_count}")
                    return True
                elif "실패" in alert_text or "오류" in alert_text:
                    log(f"  댓글 등록 실패 알림")
                    return False
            except TimeoutException:
                log("  알림창 없음 - 성공으로 처리")
                self.comment_count += 1
                log(f"  댓글 카운트 증가: {self.comment_count}")
                return True
            except Exception as e:
                log(f"  알림 처리 중 오류: {e}")
                import traceback
                traceback.print_exc()
                return False
            
            return False
                
        except Exception as e:
            log(f"  댓글 작성 중 예외 발생: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def run(self):
        """메인 실행 함수"""
        try:
            # config 다시 로드 (변경사항 반영)
            reload(config)
            
            # Tor 시작
            if config.USE_TOR:
                if not self.tor_manager.start_tor():
                    log("Tor 시작 실패! Tor 없이 진행합니다.")
                    config.USE_TOR = False
            
            self.setup_driver()
            
            log("=" * 60)
            log("디시인사이드 자동 댓글 매크로 시작")
            log(f"대상 갤러리: {len(config.GALLERIES)}개")
            for gid, gurl in config.GALLERIES:
                log(f"  - {gid}")
            log(f"댓글 내용: {config.COMMENT_TEXT}")
            log(f"닉네임: {config.NICKNAME}")
            log(f"확인 주기: {config.CHECK_INTERVAL}초")
            if config.USE_TOR:
                log(f"Tor 사용: 활성화 (IP당 댓글: {config.COMMENTS_PER_IP}개)")
            else:
                log("Tor 사용: 비활성화")
            log("=" * 60)
            
            while True:
                try:
                    log(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] 새 게시글 확인 중...")
                    
                    # 모든 갤러리 순회
                    for gallery_id, gallery_url in config.GALLERIES:
                        log(f"\n--- [{gallery_id}] 갤러리 확인 ---")
                        
                        posts = self.get_latest_posts(gallery_url)
                        
                        if not posts:
                            log(f"[{gallery_id}] 게시글을 가져오지 못했습니다.")
                            continue
                        
                        # 링크 기반으로 중복 체크
                        new_posts = [p for p in posts if not self.is_already_commented(p['link'])]
                        
                        if new_posts:
                            log(f"\n★ [{gallery_id}] 댓글 안 단 게시글 {len(new_posts)}개 발견!")
                            
                            for post in new_posts:
                                # 이미 댓글 달았는지 다시 확인 (중복 방지)
                                if self.is_already_commented(post['link']):
                                    log(f"\n건너뜀: [{post['num']}] 이미 댓글 완료")
                                    continue
                                
                                # 댓글 개수 기반 IP 변경 체크
                                if config.USE_TOR and self.comment_count >= config.COMMENTS_PER_IP:
                                    log(f"\n[IP 변경] {self.comment_count}개 댓글 완료, IP 변경 중...")
                                    if self.restart_with_new_ip():
                                        log("IP 변경 완료!")
                                    else:
                                        log("IP 변경 실패, 계속 진행...")
                                
                                log(f"\n처리 중: [{post['num']}] {post['title'][:40]}")
                                
                                success = self.write_comment(post['link'], post['num'])
                                
                                if success:
                                    log(f"✓ 댓글 작성 완료! (이번 IP: {self.comment_count}개)")
                                    # 링크 즉시 저장 (중복 방지)
                                    self.commented_links.append(post['link'])
                                    self.save_commented_links()
                                else:
                                    log(f"✗ 댓글 작성 실패")
                                    # 실패해도 링크 저장 (무한 재시도 방지)
                                    self.commented_links.append(post['link'])
                                    self.save_commented_links()
                                
                                time.sleep(config.COMMENT_DELAY)
                        else:
                            log(f"[{gallery_id}] 모든 게시글에 이미 댓글 완료.")
                    
                    log(f"\n{config.CHECK_INTERVAL}초 후 다시 확인...")
                    time.sleep(config.CHECK_INTERVAL)
                    
                except Exception as loop_error:
                    log(f"\n⚠️ 루프 중 오류 발생: {loop_error}")
                    import traceback
                    traceback.print_exc()
                    log("10초 후 재시도...")
                    time.sleep(10)
                    # 드라이버 재시작 시도
                    try:
                        self.restart_driver()
                    except:
                        pass
                
        except KeyboardInterrupt:
            log("\n\n프로그램을 종료합니다.")
        except Exception as e:
            log(f"오류 발생: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.driver:
                self.driver.quit()
                log("브라우저 종료")
            self.tor_manager.stop_tor()
            log("Tor 종료")
