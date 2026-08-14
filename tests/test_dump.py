"""claude-history-dump.py 的最小 smoke test：验证转换只留对话文本、丢弃工具噪音/压缩摘要。"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
SPEC = importlib.util.spec_from_file_location("claude_history_dump", os.path.join(SCRIPTS, "claude-history-dump.py"))
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def make_line(ev_type="user", role="user", content=None, extra=None):
    ev = {"type": ev_type, "timestamp": "2026-08-14T00:00:00.000Z", "message": {"role": role, "content": content}}
    if extra:
        ev.update(extra)
    return json.dumps(ev, ensure_ascii=False)


class TestExtractTextBlocks(unittest.TestCase):
    def test_str_content(self):
        self.assertEqual(mod.extract_text_blocks("hello"), "hello")

    def test_list_content_keeps_text_only(self):
        blocks = [
            {"type": "text", "text": "keep me"},
            {"type": "tool_use", "name": "Bash"},
            {"type": "text", "text": "keep too"},
        ]
        self.assertEqual(mod.extract_text_blocks(blocks), "keep me\nkeep too")


class TestParseJsonl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8", delete=False)
        self.path = self.tmp.name

    def tearDown(self):
        self.tmp.close()
        os.unlink(self.path)

    def write_lines(self, *lines):
        self.tmp.write("\n".join(lines) + "\n")
        self.tmp.flush()

    def test_keeps_plain_dialogue(self):
        self.write_lines(
            make_line("user", "user", "问题"),
            make_line("assistant", "assistant", [{"type": "text", "text": "回答"}]),
        )
        msgs = mod.parse_jsonl(self.path, "")
        self.assertEqual([m[1] for m in msgs], ["你", "Claude"])
        self.assertEqual(msgs[0][2], "问题")
        self.assertEqual(msgs[1][2], "回答")

    def test_drops_tool_use_from_assistant(self):
        self.write_lines(
            make_line("assistant", "assistant", [
                {"type": "tool_use", "name": "Bash"},
                {"type": "text", "text": "可见文本"},
            ]),
        )
        msgs = mod.parse_jsonl(self.path, "")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0][2], "可见文本")

    def test_drops_user_tool_result(self):
        self.write_lines(
            make_line("user", "user", [{"type": "tool_result", "content": "命令输出噪音"}]),
            make_line("user", "user", "真正的问题"),
        )
        msgs = mod.parse_jsonl(self.path, "")
        self.assertEqual([m[2] for m in msgs], ["真正的问题"])

    def test_drops_summary_and_non_conversation_events(self):
        self.write_lines(
            make_line("summary", "assistant", "压缩摘要噪音"),
            make_line("ai-title", None, None),
            make_line("user", "user", "问题"),
            make_line("assistant", "assistant", "回答", extra={"summary": "字段摘要"}),
        )
        msgs = mod.parse_jsonl(self.path, "")
        self.assertEqual([m[2] for m in msgs], ["问题", "回答"])

    def test_ignores_malformed_lines(self):
        self.write_lines(
            "not json at all",
            make_line("user", "user", "正常"),
        )
        msgs = mod.parse_jsonl(self.path, "")
        self.assertEqual(len(msgs), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
