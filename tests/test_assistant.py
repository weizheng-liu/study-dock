from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import Portal
from core import UserError
from study_assistant import ask, draft


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = Portal(self.root, {})
        self.one = self.app.db.register("student-one", "test-password-1")
        self.two = self.app.db.register("student-two", "test-password-2")
        self.item = {"source": "canvas", "course": "電気", "course_id": "17", "due_at": "2026-11-18T15:00:00Z",
                     "title": "演習", "description": "説明", "status": "pending", "id": "item-1",
                     "url": "https://nu.instructure.com/courses/17/assignments/21", "text_entry": True}
        self.cache = {"courses": [], "items": [self.item], "resources": [], "providers": {"canvas": {"state": "partial"}}}
        self.app.db.write(self.one, "cache", self.cache)

    def test_tomorrow_in_tokyo_and_incomplete_coverage(self):
        now = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)
        self.cache["items"].extend([dict(self.item, status="submitted"), dict(self.item, due_at=None)])
        result = ask(self.root, self.cache, {"question": "明天有什么作业需要提交？"}, now)
        self.assertEqual([r["url"] for r in result["sources"]], [self.item["url"]])
        self.assertIn("2026-11-19", result["answer"])
        self.assertIn("同步不完整", result["coverage"])
        self.assertIn("未排入", result["coverage"])

    @patch("study_assistant.generate", return_value="见 [1]")
    def test_grounding_and_no_shared_conversation(self, generate):
        answer = ask(self.root, self.cache, {"question": "这道题要求什么？"})
        self.assertEqual(answer["sources"][0]["title"], self.item["title"])
        self.assertEqual(generate.call_args.args[-1]["之前的对话"], [])
        self.assertIsNone(self.app.assignment(self.two, item_id=self.item["id"]))

    def test_draft_only_for_bound_user_assignment_and_account(self):
        binding = {"source":"canvas", "origin":self.app.canvas, "account_hash":"a"*64}
        self.app.browser.bind(self.one, binding)
        self.app.db.write(self.one, "cache", self.cache)
        self.app.save_text_draft(self.one, self.item, "edited")
        self.assertEqual(self.app.browser_draft(self.one, dict(binding, url=self.item["url"]))["text"], "edited")
        for uid, body in [(self.two, binding), (self.one, dict(binding, account_hash="b"*64))]:
            with self.assertRaises(UserError):
                self.app.browser_draft(uid, dict(body, url=self.item["url"]))
        with self.assertRaises(UserError):
            draft(self.root, dict(self.item, text_entry=False))
        self.app.browser_draft(self.one, dict(binding, url=self.item["url"], consume=True))
        with self.assertRaises(UserError):
            self.app.browser_draft(self.one, dict(binding, url=self.item["url"], consume=True))
