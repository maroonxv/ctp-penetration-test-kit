import logging
import pytest
from src.logging.color import color_for_log


class TestColorForLog:
    """Tests for the unified color_for_log function (merged from worker._color_for and socket_handler inline logic)."""

    def test_error_level_returns_red(self):
        assert color_for_log(logging.ERROR, "some error") == "#ff4d4d"

    def test_critical_level_returns_red(self):
        assert color_for_log(logging.CRITICAL, "critical issue") == "#ff4d4d"

    def test_warning_level_returns_orange(self):
        assert color_for_log(logging.WARNING, "some warning") == "#ffbf00"

    def test_ctp_callback_onrtn_returns_blue(self):
        assert color_for_log(logging.INFO, "OnRtnOrder received") == "#00ccff"

    def test_ctp_callback_onrsp_returns_blue(self):
        assert color_for_log(logging.INFO, "OnRspOrderInsert") == "#00ccff"

    def test_ctp_callback_chinese_received(self):
        assert color_for_log(logging.INFO, "收到委托回报") == "#00ccff"

    def test_ctp_callback_chinese_callback(self):
        assert color_for_log(logging.INFO, "回调处理完成") == "#00ccff"

    def test_bracket_marker_returns_green(self):
        assert color_for_log(logging.INFO, "【测试用例 1】") == "#00ff00"

    def test_success_english_returns_green(self):
        assert color_for_log(logging.INFO, "Connection Success") == "#00ff00"

    def test_success_chinese_returns_green(self):
        assert color_for_log(logging.INFO, "连接成功") == "#00ff00"

    def test_default_returns_gray(self):
        assert color_for_log(logging.INFO, "normal log message") == "#cccccc"

    def test_debug_level_default_returns_gray(self):
        assert color_for_log(logging.DEBUG, "debug info") == "#cccccc"

    def test_error_takes_priority_over_keywords(self):
        """ERROR level should return red even if message contains callback keywords."""
        assert color_for_log(logging.ERROR, "OnRtnOrder error") == "#ff4d4d"

    def test_warning_takes_priority_over_keywords(self):
        """WARNING level should return orange even if message contains success keywords."""
        assert color_for_log(logging.WARNING, "Success with warning") == "#ffbf00"
