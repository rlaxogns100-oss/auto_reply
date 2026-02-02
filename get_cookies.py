#!/usr/bin/env python3
"""
네이버 쿠키 추출 스크립트 (로컬 실행용)

이 스크립트는 로컬 컴퓨터에서 실행하여 네이버 로그인 쿠키를 추출합니다.
추출된 쿠키 파일(naver_cookies.pkl)을 서버로 업로드하면
서버에서 headless 모드로 자동 로그인이 가능합니다.

사용법:
1. 로컬에서 이 스크립트 실행: python get_cookies.py
2. 브라우저가 열리면 60초 안에 네이버 로그인
3. naver_cookies.pkl 파일이 생성됨
4. 이 파일을 서버의 auto_reply 폴더로 복사 (scp 사용)

예시:
scp naver_cookies.pkl azureuser@52.141.16.217:~/auto_reply/
"""

import pickle
import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

def main():
    print("=" * 50)
    print("네이버 쿠키 추출기")
    print("=" * 50)
    
    # 브라우저 실행 (headless 아님 - 로그인을 위해)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    
    try:
        # 네이버 로그인 페이지로 이동
        driver.get("https://nid.naver.com/nidlogin.login")
        
        print("\n" + "=" * 50)
        print("👉 브라우저에서 네이버 로그인을 완료하세요!")
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
            cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "naver_cookies.pkl")
            
            with open(cookie_file, "wb") as f:
                pickle.dump(cookies, f)
            
            print("\n" + "=" * 50)
            print("✅ 쿠키 저장 완료!")
            print(f"📁 파일 위치: {cookie_file}")
            print(f"🍪 쿠키 개수: {len(cookies)}개")
            print("=" * 50)
            print("\n다음 단계:")
            print("1. 이 파일을 서버로 복사하세요:")
            print(f'   scp "{cookie_file}" azureuser@52.141.16.217:~/auto_reply/')
            print("\n2. 서버에서 봇 실행:")
            print("   cd ~/auto_reply && python main.py")
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
