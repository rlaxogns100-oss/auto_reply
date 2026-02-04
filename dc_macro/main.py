#!/usr/bin/env python3
"""
디시인사이드 자동 댓글 매크로
한석원 갤러리의 모든 최신 글에 자동으로 댓글을 답니다.
"""

from dc_crawler import DCInsideCrawler


def main():
    crawler = DCInsideCrawler()
    crawler.run()


if __name__ == "__main__":
    main()
