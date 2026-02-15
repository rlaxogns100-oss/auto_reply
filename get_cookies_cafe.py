#!/usr/bin/env python3
"""
계정별 네이버 쿠키 추출 스크립트 (로컬 실행용)

사용법:
1. python get_cookies_cafe.py horse324   # 수만휘 계정
2. python get_cookies_cafe.py hao_yj     # 수험생카페 계정
3. python get_cookies_cafe.py herry0515  # 맘카페 계정

브라우저가 열리면 60초 안에 해당 계정으로 네이버 로그인하세요.
"""

import pickle
import time
import os
import sys
import glob
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# 계정 정보 (account_id 기준)
ACCOUNTS = {
    "horse324": {
        "name": "수만휘 계정 (horse324)",
        "naver_id": "horse324",
    },
    "hao_yj": {
        "name": "수험생카페 계정 (hao_yj)",
        "naver_id": "hao_yj",
    },
    "herry0515": {
        "name": "맘카페 계정 (herry0515)",
        "naver_id": "herry0515",
    }
}

def get_chromedriver_path():
    """webdriver-manager 캐시에서 올바른 chromedriver 경로 찾기"""
    wdm_path = os.path.expanduser("~/.wdm/drivers/chromedriver")
    if os.path.exists(wdm_path):
        # chromedriver 파일 찾기 (THIRD_PARTY_NOTICES.chromedriver 제외)
        chromedriver_paths = glob.glob(f"{wdm_path}/**/chromedriver", recursive=True)
        valid_paths = [p for p in chromedriver_paths if not p.endswith('.chromedriver') and os.path.isfile(p)]
        if valid_paths:
            # 가장 최신 파일 선택
            return max(valid_paths, key=os.path.getmtime)
    return None

def main():
    if len(sys.argv) < 2:
        print("사용법: python get_cookies_cafe.py <account_id>")
        print("지원 계정:")
        for account_id, info in ACCOUNTS.items():
            print(f"  - {account_id}: {info['name']}")
        sys.exit(1)
    
    account_id = sys.argv[1]
    
    if account_id not in ACCOUNTS:
        print(f"❌ 지원하지 않는 계정 ID: {account_id}")
        print("지원 계정:", list(ACCOUNTS.keys()))
        sys.exit(1)
    
    account = ACCOUNTS[account_id]
    
    print("=" * 50)
    print(f"네이버 쿠키 추출기 - {account['name']}")
    print(f"계정: {account['naver_id']}")
    print("=" * 50)
    
    # 브라우저 실행 (headless 아님 - 로그인을 위해)
    # 먼저 캐시된 chromedriver 경로 확인
    chromedriver_path = get_chromedriver_path()
    if chromedriver_path:
        print(f"캐시된 chromedriver 사용: {chromedriver_path}")
        driver = webdriver.Chrome(service=Service(chromedriver_path))
    else:
        print("chromedriver 다운로드 중...")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    
    try:
        # 네이버 로그인 페이지로 이동
        driver.get("https://nid.naver.com/nidlogin.login")
        
        print("\n" + "=" * 50)
        print(f"👉 브라우저에서 {account['naver_id']} 계정으로 로그인하세요!")
        print("⏱️  제한 시간: 60초")
        print("=" * 50 + "\n")
        
        # 60초 대기 (이 시간 동안 직접 로그인)
        for i in range(60, 0, -1):
            print(f"\r남은 시간: {i}초...", end="", flush=True)
            time.sleep(1)
        
        print("\n\n쿠키 추출 중...")
        
        # 로그인 확인
        driver.get("https://naver.com")
        time.sleep(2)
        
        page_source = driver.page_source
        if "로그아웃" in page_source or "내정보" in page_source or "MY" in page_source:
            # 쿠키 저장
            cookies = driver.get_cookies()
            
            # accounts/ 디렉토리에 계정별로 저장
            script_dir = os.path.dirname(os.path.abspath(__file__))
            accounts_dir = os.path.join(script_dir, "accounts")
            os.makedirs(accounts_dir, exist_ok=True)
            
            cookie_file = os.path.join(accounts_dir, f"{account_id}_cookies.pkl")
            
            with open(cookie_file, "wb") as f:
                pickle.dump(cookies, f)
            
            print("\n" + "=" * 50)
            print("✅ 쿠키 저장 완료!")
            print(f"📁 파일 위치: {cookie_file}")
            print(f"🍪 쿠키 개수: {len(cookies)}개")
            print("=" * 50)
            print("\n다음 단계:")
            print("1. 이 파일을 서버로 복사하세요:")
            print(f'   scp "{cookie_file}" azureuser@52.141.16.217:~/auto_reply/accounts/')
            print("=" * 50)
        else:
            print("\n❌ 로그인이 완료되지 않았습니다.")
            print("다시 시도해 주세요.")
            
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
    finally:
        driver.quit()
        print("\n브라우저 종료됨")

if __name__ == "__main__":
    main()
