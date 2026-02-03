"""
Answer Agent가 빈 응답을 반환하면 댓글을 건너뛰는지 검증하는 테스트.
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

# main 모듈 로드 전에 config mock (API 키 등 불필요)
with patch.dict("os.environ", {}, clear=False):
    pass

# main을 import하면 query_agent, answer_agent 등이 생성되므로
# 패치는 main.answer_agent.generate_content 로 함
sys.path.insert(0, ".")


class TestAnswerAgentEmpty(unittest.TestCase):
    """Answer Agent 빈 응답 시 None 반환 (댓글 생략) 테스트"""

    @patch("main.answer_agent")
    @patch("main.generate_function_calls")
    @patch("main.get_rag_context_from_functions")
    def test_empty_answer_returns_none(
        self, mock_rag, mock_generate_calls, mock_answer_agent
    ):
        # Query Agent는 호출할 말이 있다고 가정 (비빈 function_calls)
        mock_generate_calls.return_value = [{"name": "search_something", "args": {}}]
        mock_rag.return_value = {}
        # Answer Agent는 빈 문자열 반환 (할 말 없음)
        mock_response = MagicMock()
        mock_response.text = ""
        mock_answer_agent.generate_content.return_value = mock_response

        from main import analyze_and_generate_reply

        out = analyze_and_generate_reply("테스트 제목", "테스트 본문", use_rag=False)
        self.assertIsNone(out, "Answer Agent 빈 응답 시 None 반환해야 함")

    @patch("main.answer_agent")
    @patch("main.generate_function_calls")
    @patch("main.get_rag_context_from_functions")
    def test_whitespace_only_answer_returns_none(
        self, mock_rag, mock_generate_calls, mock_answer_agent
    ):
        mock_generate_calls.return_value = [{"name": "search_something", "args": {}}]
        mock_rag.return_value = {}
        mock_response = MagicMock()
        mock_response.text = "   \n\t  "
        mock_answer_agent.generate_content.return_value = mock_response

        from main import analyze_and_generate_reply

        out = analyze_and_generate_reply("테스트 제목", "테스트 본문", use_rag=False)
        self.assertIsNone(out, "공백만 있는 응답도 None 반환해야 함")

    @patch("main.answer_agent")
    @patch("main.generate_function_calls")
    @patch("main.get_rag_context_from_functions")
    def test_non_empty_answer_returns_string(
        self, mock_rag, mock_generate_calls, mock_answer_agent
    ):
        mock_generate_calls.return_value = [{"name": "search_something", "args": {}}]
        mock_rag.return_value = {}
        mock_response = MagicMock()
        mock_response.text = "이 점수면 OO대는 안정적이에요."
        mock_answer_agent.generate_content.return_value = mock_response

        from main import analyze_and_generate_reply

        out = analyze_and_generate_reply("테스트 제목", "테스트 본문", use_rag=False)
        self.assertIsNotNone(out)
        self.assertIn("수험생 전문 ai에 물어보니까 이러네요", out)
        self.assertIn("이 점수면 OO대는 안정적이에요.", out)


if __name__ == "__main__":
    unittest.main()
