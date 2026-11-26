"""Exercise authorization -> read-only API -> private cache with simulated providers.

These tests do not establish that the school's OAuth app is approved or live.
"""
import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import EMPTY, TOKEN_EXPIRED, Portal
from core import SCOPES, UserError, export_ics, html_links


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.portal = Portal(Path(self.temp.name), {
            "canvas": {"client_id": "canvas-client", "client_secret": "canvas-secret"},
            "classroom": {"client_id": "google-client", "client_secret": "google-secret"}})
        self.uid = self.portal.db.register("student-one", "test-password-one")
        self.other_uid = self.portal.db.register("student-two", "test-password-two")

    def tearDown(self):
        self.portal.executor.shutdown(wait=True)
        self.temp.cleanup()

    def query(self, source):
        url = self.portal.connect_url(self.uid, "session-one", source)
        params = parse_qs(urlsplit(url).query)
        return params, {"state": params["state"], "code": [source + "-code"]}

    def wait_for_sync(self):
        deadline = time.monotonic() + 5
        while self.portal.state(self.uid)["syncing"] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.portal.state(self.uid)["syncing"])

    def fake_read_api(self, url, token="", form=None):
        parsed = urlsplit(url)
        if parsed.hostname == "nu.instructure.com":
            self.assertEqual(token, "canvas-access")
            path = parsed.path
            if path == "/api/v1/courses":
                return [{"id": 11, "name": "电子回路"}], {}
            if path.endswith("/assignments"):
                return [{"id": 101, "name": "计算题", "description": '<p>写出计算步骤。</p><a href="/courses/11/files/7">题目 PDF</a>',
                         "due_at": "2026-11-19T23:59:00+09:00", "submission": {"workflow_state": "unsubmitted"}}], {}
            if path.endswith("/discussion_topics"):
                return [{"id": 5, "title": "上课通知", "message": "准备计算器。", "html_url": "https://nu.instructure.com/courses/11/discussion_topics/5"}], {}
            if path.endswith("/files"):
                return [{"id": 7, "display_name": "题目.pdf"}], {}
            if path.endswith("/pages"):
                return [{"page_id": 8, "title": "参考页", "html_url": "https://nu.instructure.com/courses/11/pages/reference"}], {}
            if path.endswith("/modules"):
                return [{"id": 9, "name": "第六回", "items_count": 1, "items": [{"id": 10, "title": "讲义", "html_url": "https://nu.instructure.com/courses/11/files/7"}]}], {}
        if parsed.hostname == "classroom.googleapis.com":
            self.assertEqual(token, "classroom-access")
            path = parsed.path
            if path == "/v1/courses":
                return {"courses": [{"id": "21", "name": "微观经济学"}]}, {}
            if path.endswith("/courseWork"):
                return {"courseWork": [{"id": "201", "title": "需求练习", "description": "解释需求曲线。",
                        "dueDate": {"year": 2026, "month": 11, "day": 20}, "dueTime": {"hours": 14, "minutes": 59}}]}, {}
            if path.endswith("/studentSubmissions"):
                return {"studentSubmissions": [{"courseWorkId": "201", "state": "TURNED_IN"}]}, {}
            if path.endswith("/courseWorkMaterials"):
                return {"courseWorkMaterial": [{"id": "202", "title": "讲义", "description": "阅读第二章。"}]}, {}
            if path.endswith("/announcements"):
                return {"announcements": [{"id": "203", "text": "下周小测。"}]}, {}
        raise AssertionError("Unexpected read-only API request: " + parsed.path)

    @patch("core.request_json")
    @patch("app.request_json")
    def test_both_authorizations_fetch_requirements_resources_and_private_calendar(self, exchange, read_api):
        read_api.side_effect = self.fake_read_api
        for source in ("canvas", "classroom"):
            params, query = self.query(source)
            exchange.return_value = ({"access_token": source + "-access", "refresh_token": source + "-refresh",
                                      "expires_in": 3600, "scope": " ".join(SCOPES)}, {})
            self.portal.callback(self.uid, "session-one", source, query)
            self.wait_for_sync()
            sent = exchange.call_args.kwargs["form"]
            self.assertEqual(sent["code"], source + "-code")
            self.assertEqual(sent["redirect_uri"], self.portal.base_url + f"/oauth/{source}/callback")
            if source == "classroom":
                challenge = base64.urlsafe_b64encode(hashlib.sha256(sent["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                self.assertEqual(params["code_challenge"], [challenge])
            with self.assertRaises(UserError):
                self.portal.callback(self.uid, "session-one", source, query)
        state = self.portal.state(self.uid)
        self.assertEqual(len(state["items"]), 2)
        self.assertEqual({item["source"] for item in state["items"]}, {"canvas", "classroom"})
        canvas = next(item for item in state["items"] if item["source"] == "canvas")
        self.assertIn("计算步骤", canvas["description"])
        self.assertEqual(canvas["attachments"][0], {"title": "题目 PDF", "url": "https://nu.instructure.com/courses/11/files/7"})
        self.assertEqual({item["kind"] for item in state["resources"]}, {"announcement", "file", "page", "module", "material"})
        self.assertTrue(all(provider["state"] == "ok" for provider in state["providers"].values()))
        self.assertNotIn("canvas-access", str(state))
        self.assertEqual(self.portal.state(self.other_uid)["items"], [])
        self.assertEqual(export_ics(state["items"]).count(b"BEGIN:VEVENT"), 2)
        self.portal.disconnect(self.uid, "canvas")
        state = self.portal.state(self.uid)
        self.assertEqual({item["source"] for item in state["items"]}, {"classroom"})
        self.assertEqual({item["source"] for item in state["resources"]}, {"classroom"})
        self.assertFalse(state["connections"]["canvas"]["connected"])
        self.assertTrue(state["connections"]["classroom"]["connected"])

    @patch("app.request_json")
    def test_refresh_preserves_offline_token_and_other_users_authorization(self, request):
        for source in ("canvas", "classroom"):
            self.portal.db.write(self.uid, "secrets", {source: {"access_token": "expired", "refresh_token": "keep-refresh", "expires_at": 0}})
            self.portal.db.write(self.other_uid, "secrets", {source: {"access_token": "other-user-token", "refresh_token": "other-refresh", "expires_at": 9e9}})
            request.return_value = ({"access_token": "new-access", "expires_in": 3600}, {})
            self.assertEqual(self.portal.access_token(self.uid, source), "new-access")
            saved = self.portal.db.read(self.uid, "secrets", {})[source]
            self.assertEqual(saved["refresh_token"], "keep-refresh")
            self.assertGreater(saved["expires_at"], time.time() + 3500)
            self.assertEqual(self.portal.access_token(self.other_uid, source), "other-user-token")
            self.assertEqual(request.call_args.kwargs["form"]["refresh_token"], "keep-refresh")

    @patch("app.request_json")
    def test_incomplete_google_consent_keeps_previous_connection_and_cache(self, request):
        self.portal.db.write(self.uid, "secrets", {"classroom": {"access_token": "previous", "refresh_token": "previous-refresh", "expires_at": 9e9}})
        self.portal.db.write(self.uid, "cache", dict(EMPTY, items=[{"id": "cached", "source": "classroom"}]))
        _, query = self.query("classroom")
        request.return_value = ({"access_token": "partial", "refresh_token": "partial-refresh", "scope": SCOPES[0]}, {})
        with self.assertRaises(UserError):
            self.portal.callback(self.uid, "session-one", "classroom", query)
        self.assertEqual(self.portal.db.read(self.uid, "secrets", {})["classroom"]["access_token"], "previous")
        self.assertEqual(self.portal.db.read(self.uid, "cache", EMPTY)["items"][0]["id"], "cached")

    @patch("core.request_json")
    @patch("app.request_json")
    def test_canvas_personal_token_syncs_without_oauth_app_or_browser(self, verify, read_api):
        portal = Portal(Path(self.temp.name) / "token", {})  # no OAuth client configured at all
        uid = portal.db.register("token-student", "test-password-one")
        portal.db.write(uid, "browser", {"bindings": {"canvas": {"label": "old", "account_hash": "x"}}, "requests": {}})
        verify.return_value = ({"id": 42, "name": "山田 太郎"}, {})
        token = "1234~" + "a" * 60
        # Personal tokens are sent as-is to Canvas and never go through an OAuth refresh.
        read_api.side_effect = lambda url, sent="", form=None: self.fake_read_api(
            url, "canvas-access" if sent == token else sent, form)
        with self.assertRaises(UserError):
            portal.save_canvas_token(uid, "not a token")
        self.assertEqual(portal.save_canvas_token(uid, f"  {token}\n"), {"ok": True, "label": "山田 太郎"})
        self.assertEqual(verify.call_args.args, ("https://nu.instructure.com/api/v1/users/self", token))
        portal.executor.shutdown(wait=True)
        state = portal.state(uid)
        self.assertEqual(state["connections"]["canvas"]["mode"], "token")
        self.assertEqual(state["connections"]["canvas"]["label"], "山田 太郎")
        self.assertNotIn("canvas", state["browser"]["bindings"])
        self.assertEqual([item["title"] for item in state["items"]], ["计算题"])
        self.assertEqual(state["items"][0]["due_at"], "2026-11-19T14:59:00+00:00")
        self.assertNotIn(token, str(state))
        self.assertEqual(portal.state(uid)["providers"]["canvas"]["state"], "ok")
        self.assertEqual(portal.access_token(uid, "canvas"), token)

    @patch("core.request_json")
    @patch("app.request_json")
    def test_canvas_token_expiry_is_tracked_and_reported(self, verify, read_api):
        from datetime import datetime, timedelta, timezone
        portal = Portal(Path(self.temp.name) / "expiry", {})
        uid = portal.db.register("expiry-student", "test-password-one")
        token = "1234~" + "b" * 60
        verify.return_value = ({"id": 7, "name": "学生"}, {})
        read_api.side_effect = UserError("授权已过期，请重新连接账号。")
        today = datetime.now(timezone(timedelta(hours=9))).date()
        with self.assertRaises(UserError):
            portal.save_canvas_token(uid, token, (today - timedelta(days=1)).isoformat())
        with self.assertRaises(UserError):
            portal.save_canvas_token(uid, token, "30 days")
        portal.save_canvas_token(uid, token, (today + timedelta(days=2)).isoformat())
        portal.executor.shutdown(wait=True)
        canvas = portal.state(uid)["connections"]["canvas"]
        self.assertTrue(canvas["token_expiring"])
        self.assertEqual(canvas["token_days_left"], 2)
        # A 401 from Canvas (token deleted early) becomes an explicit "regenerate" message.
        self.assertEqual(canvas["status"]["message"], TOKEN_EXPIRED)
        self.assertTrue(canvas["status"]["token_expired"])
        # Past the recorded expiry, no request is sent at all.
        secret = portal.db.read(uid, "secrets", {})
        secret["canvas"]["expires_at"] = time.time() - 60
        portal.db.write(uid, "secrets", secret)
        read_api.reset_mock()
        portal.sync(uid)
        read_api.assert_not_called()
        canvas = portal.state(uid)["connections"]["canvas"]
        self.assertEqual(canvas["token_days_left"], -1)
        self.assertEqual(canvas["status"]["message"], TOKEN_EXPIRED)

    @patch("core.request_json")
    def test_canvas_tabs_hidden_from_students_are_not_warnings(self, read_api):
        from core import fetch_canvas

        def hidden(url, token="", form=None):
            path = urlsplit(url).path
            if path.endswith("/files"):
                raise UserError("账号或学校未允许此接口访问，请检查授权或联系学校管理员。", status=403)
            if path.endswith("/pages"):
                raise UserError("平台返回 HTTP 404，请稍后重试。", status=404)
            if path.endswith("/discussion_topics"):
                raise UserError("平台返回 HTTP 500，请稍后重试。", status=500)
            return self.fake_read_api(url, token, form)
        read_api.side_effect = hidden
        batch = fetch_canvas("https://nu.instructure.com", "canvas-access")
        self.assertEqual(len(batch.items), 1)
        self.assertEqual({r["kind"] for r in batch.resources}, {"module"})
        self.assertEqual(batch.failed_resources, {"11:announcement"})
        self.assertEqual(len(batch.warnings), 1)

    @patch("core.request_json")
    @patch("app.request_json")
    def test_classroom_core_scopes_suffice_and_optional_kinds_are_skipped(self, exchange, read_api):
        read_api.side_effect = self.fake_read_api
        _, query = self.query("classroom")
        exchange.return_value = ({"access_token": "classroom-access", "refresh_token": "r", "expires_in": 3600,
                                  "scope": " ".join(SCOPES[:2])}, {})
        self.portal.callback(self.uid, "session-one", "classroom", query)
        self.wait_for_sync()
        state = self.portal.state(self.uid)
        self.assertEqual(state["connections"]["classroom"]["mode"], "oauth")
        self.assertEqual(state["providers"]["classroom"]["state"], "ok")
        self.assertEqual(state["items"][0]["due_at"], "2026-11-20T14:59:00+00:00")
        self.assertEqual(state["resources"], [])
        called = {urlsplit(c.args[0]).path.rsplit("/", 1)[-1] for c in read_api.call_args_list}
        self.assertNotIn("announcements", called)

    def test_attachment_relative_paths_and_titles(self):
        links = html_links('<a href="../files/7"><b>题目</b> PDF</a><a href="#note">注</a><a href="javascript:bad()">坏链接</a>',
                           "https://nu.instructure.com/courses/11/assignments/101")
        self.assertEqual(links, [{"title": "题目 PDF", "url": "https://nu.instructure.com/courses/11/files/7"}])


if __name__ == "__main__":
    unittest.main()
