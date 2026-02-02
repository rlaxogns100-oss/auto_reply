# Auto Reply 봇 서버 배포 가이드

## 1. 서버 환경 준비 (Ubuntu)

### 1.1 SSH 접속

```bash
ssh -i "/Users/rlaxogns100/Desktop/김태훈/uniroad-server_key_fixed.pem" azureuser@52.141.16.217
```

### 1.2 Chrome 설치

```bash
# 패키지 업데이트
sudo apt update

# Chrome 다운로드 및 설치
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install ./google-chrome-stable_current_amd64.deb -y

# 설치 확인
google-chrome --version
```

### 1.3 Python 패키지 설치

```bash
# pip 업그레이드
pip install --upgrade pip

# 필요한 패키지 설치
pip install selenium webdriver-manager google-generativeai requests
```

---

## 2. 쿠키 생성 (로컬 PC에서 실행)

### 2.1 로컬에서 쿠키 추출

```bash
# auto_reply 디렉토리로 이동
cd /Users/rlaxogns100/Desktop/Projects/auto_reply

# 쿠키 추출 스크립트 실행
python get_cookies.py
```

브라우저가 열리면 **60초 안에 네이버 로그인**을 완료하세요.
`naver_cookies.pkl` 파일이 생성됩니다.

### 2.2 쿠키 파일 서버로 업로드

```bash
scp -i "/Users/rlaxogns100/Desktop/김태훈/uniroad-server_key_fixed.pem" \
    /Users/rlaxogns100/Desktop/Projects/auto_reply/naver_cookies.pkl \
    azureuser@52.141.16.217:~/auto_reply/
```

---

## 3. 봇 코드 서버로 배포

### 3.1 auto_reply 폴더 업로드

```bash
# 전체 폴더 업로드
scp -i "/Users/rlaxogns100/Desktop/김태훈/uniroad-server_key_fixed.pem" -r \
    /Users/rlaxogns100/Desktop/Projects/auto_reply \
    azureuser@52.141.16.217:~/
```

### 3.2 config.py 확인

서버에서 `config.py`가 올바르게 설정되었는지 확인:

```bash
ssh -i "..." azureuser@52.141.16.217
cat ~/auto_reply/config.py
```

필요시 수정:
```python
# config.py
NAVER_ID = "your_naver_id"
NAVER_PW = "your_naver_pw"
GEMINI_API_KEY = "your_gemini_api_key"
CLUB_ID = "10197921"  # 수만휘 카페 ID
BACKEND_URL = "http://localhost:8000"  # 또는 실제 백엔드 URL
```

---

## 4. 봇 실행

### 4.1 수동 실행 (테스트용)

```bash
cd ~/auto_reply
HEADLESS=true python main.py
```

### 4.2 웹 UI로 실행

uniroad 백엔드가 실행 중이면:
1. https://uni2road.com/auto-reply 접속
2. 관리자 로그인 (김도균 계정)
3. "봇 시작" 버튼 클릭

### 4.3 백그라운드 실행 (systemd 서비스)

```bash
# 서비스 파일 생성
sudo nano /etc/systemd/system/auto-reply-bot.service
```

내용:
```ini
[Unit]
Description=Auto Reply Bot
After=network.target

[Service]
Type=simple
User=azureuser
WorkingDirectory=/home/azureuser/auto_reply
Environment=HEADLESS=true
ExecStart=/usr/bin/python3 /home/azureuser/auto_reply/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

서비스 등록 및 시작:
```bash
sudo systemctl daemon-reload
sudo systemctl enable auto-reply-bot
sudo systemctl start auto-reply-bot

# 상태 확인
sudo systemctl status auto-reply-bot

# 로그 확인
sudo journalctl -u auto-reply-bot -f
```

---

## 5. 봇 관리

### 5.1 웹 UI (권장)

https://uni2road.com/auto-reply 에서:
- 봇 시작/중지
- 댓글 딜레이 설정
- 댓글 기록 확인

### 5.2 CLI 명령어

```bash
# 봇 상태 확인
sudo systemctl status auto-reply-bot

# 봇 시작
sudo systemctl start auto-reply-bot

# 봇 중지
sudo systemctl stop auto-reply-bot

# 로그 실시간 확인
sudo journalctl -u auto-reply-bot -f

# 댓글 기록 확인
cat ~/auto_reply/comment_history.json | python -m json.tool | tail -50
```

---

## 6. 문제 해결

### 쿠키 만료

쿠키는 보통 1-2주 후 만료됩니다. 만료 시:
1. 로컬에서 `get_cookies.py` 다시 실행
2. 새 쿠키 파일 서버로 업로드
3. 봇 재시작

### Chrome 크래시

```bash
# Chrome 프로세스 확인
ps aux | grep chrome

# 좀비 프로세스 정리
pkill -9 chrome
pkill -9 chromedriver
```

### 봇이 안 멈출 때

```bash
# 정지 플래그 파일 생성 (graceful shutdown)
touch ~/auto_reply/.stop_bot

# 또는 강제 종료
pkill -f "python main.py"
```

---

## 7. 파일 구조

```
~/auto_reply/
├── main.py                 # 메인 봇 스크립트
├── config.py               # 설정 (API 키, 계정 정보)
├── get_cookies.py          # 쿠키 추출 (로컬용)
├── bot_config.json         # 런타임 설정
├── naver_cookies.pkl       # 네이버 로그인 쿠키
├── comment_history.json    # 댓글 기록
├── visited_history.txt     # 방문한 게시글 기록
└── SERVER_DEPLOY.md        # 이 문서
```

---

## 8. 보안 주의사항

- `config.py`와 `naver_cookies.pkl`은 절대 공개하지 마세요
- `.gitignore`에 민감한 파일이 포함되어 있는지 확인하세요
- 서버 방화벽 설정을 확인하세요
