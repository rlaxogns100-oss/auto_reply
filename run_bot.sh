#!/bin/bash
# ============================================
# Auto Reply Bot Wrapper Script
# - 시작 전 좀비 프로세스 자동 정리
# - 크래시 시 자동 재시작 (최대 5회)
# - 로그 로테이션
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/bot.log"
MAX_RETRIES=5
RETRY_DELAY=10

# 로그 함수
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Chrome 좀비 프로세스 정리
cleanup_chrome() {
    log "Chrome 프로세스 정리 중..."
    pkill -9 chrome 2>/dev/null
    pkill -9 chromedriver 2>/dev/null
    pkill -9 -f 'google-chrome' 2>/dev/null
    rm -rf "$SCRIPT_DIR"/chrome_data_* 2>/dev/null
    rm -rf /tmp/com.google.Chrome.* 2>/dev/null
    rm -rf /tmp/.org.chromium.* 2>/dev/null
    rm -rf /tmp/org.chromium.* 2>/dev/null
    sleep 2
    log "Chrome 정리 완료"
}

# 로그 로테이션 (10MB 초과 시)
rotate_log() {
    if [ -f "$LOG_FILE" ]; then
        LOG_SIZE=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null)
        if [ "$LOG_SIZE" -gt 10485760 ]; then
            mv "$LOG_FILE" "$LOG_FILE.old"
            log "로그 로테이션 완료"
        fi
    fi
}

# 메인 실행
main() {
    rotate_log
    log "===== 봇 시작 $(date -Iseconds) ====="
    
    # 시작 전 정리
    cleanup_chrome
    
    RETRY_COUNT=0
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        log "봇 실행 시도 #$((RETRY_COUNT + 1))/$MAX_RETRIES"
        
        # 봇 실행
        HEADLESS=true python3 main.py 2>&1 | tee -a "$LOG_FILE"
        EXIT_CODE=${PIPESTATUS[0]}
        
        if [ $EXIT_CODE -eq 0 ]; then
            log "봇 정상 종료 (exit code: 0)"
            break
        fi
        
        RETRY_COUNT=$((RETRY_COUNT + 1))
        log "봇 비정상 종료 (exit code: $EXIT_CODE), 재시작 대기 중..."
        
        if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
            # 재시작 전 정리
            cleanup_chrome
            log "${RETRY_DELAY}초 후 재시작..."
            sleep $RETRY_DELAY
        fi
    done
    
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        log "최대 재시도 횟수($MAX_RETRIES) 초과, 봇 종료"
    fi
    
    log "===== 봇 종료 $(date -Iseconds) ====="
}

# 시그널 핸들러
trap 'log "종료 신호 수신"; cleanup_chrome; exit 0' SIGTERM SIGINT

main "$@"
