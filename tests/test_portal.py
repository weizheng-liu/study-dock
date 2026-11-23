import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import EMPTY, Portal, make_server
from core import (Batch, JST, UserError, canvas_assignment, canvas_pages, canvas_resources,
                  classroom_assignment, export_ics, google_attachments, google_pages,
                  merge_batch, merge_resources, parse_time)
from storage import Database, protect


def work(ident="a", source="canvas", course="1", due="2026-11-18T14:59:00+00:00"):
    return {"id": ident, "source": source, "course_id": course, "course": "电子回路",
            "title": "演习,第六回;要求\n第二行", "description": "计算电流\n写明步骤",
            "due_at": due, "status": "pending", "url": "https://nu.instructure.com/courses/1", "attachments": []}


class CoreTests(unittest.TestCase):
    def test_google_utc_crosses_local_date(self):
        item = classroom_assignment({"id": "1"}, {"id": "1", "dueDate": {"year": 2026, "month": 11, "day": 18},
                                    "dueTime": {"hours": 23, "minutes": 59}}, None)
        self.assertEqual(parse_time(item["due_at"]).astimezone(JST).strftime("%Y-%m-%d %H:%M"), "2026-11-19 08:59")
        self.assertEqual(item["status"], "unknown")

    def test_google_zero_hour_is_midnight_not_default(self):
        item = classroom_assignment({"id": "1"}, {"id": "1", "dueDate": {"year": 2026, "month": 11, "day": 18}, "dueTime": {}}, {})
        self.assertEqual(parse_time(item["due_at"]).hour, 0)

    def test_google_omitted_time_defaults_utc_2359(self):
        item = classroom_assignment({"id": "1"}, {"id": "1", "dueDate": {"year": 2026, "month": 11, "day": 18}}, {})
        self.assertEqual(parse_time(item["due_at"]).strftime("%H:%M"), "23:59")

    def test_no_due_date_is_not_invented(self):
        item = classroom_assignment({"id": "1"}, {"id": "1"}, None)
        self.assertIsNone(item["due_at"])
        self.assertNotIn(b"VEVENT", export_ics([item]))

    def test_canvas_user_specific_deadline_and_grade(self):
        raw = {"id": 1, "due_at": "2026-11-18T23:59:00+09:00", "submission": {"workflow_state": "graded"},
               "description": '<p>计算电流</p><script>bad()</script><a href="javascript:bad()">bad</a><a href="https://example.com/a">附件</a>'}
        item = canvas_assignment("https://nu.instructure.com", {"id": "1"}, raw)
        self.assertEqual(item["due_at"], "2026-11-18T14:59:00+00:00")
        self.assertEqual(item["status"], "graded")  # A grade alone does not prove submission.
        self.assertNotIn("bad()", item["description"])
        self.assertEqual(len(item["attachments"]), 1)

    @patch("core.request_json")
    def test_canvas_pagination_and_credential_origin(self, request):
        request.side_effect = [([1], {"Link": '<https://nu.instructure.com/api/v1/courses?page=2>; rel="next"'}), ([2], {})]
        self.assertEqual(canvas_pages("https://nu.instructure.com/api/v1/courses", "secret"), [1, 2])
        request.side_effect = [([], {"Link": '<https://evil.example/page>; rel="next"'})]
        with self.assertRaises(UserError):
            canvas_pages("https://nu.instructure.com/api/v1/courses", "secret")

    @patch("core.request_json")
    def test_google_pagination_keeps_query(self, request):
        request.side_effect = [({"courses": [1], "nextPageToken": "abc"}, {}), ({"courses": [2]}, {})]
        self.assertEqual(google_pages("https://classroom.googleapis.com/v1/courses", "secret", "courses", {"studentId": "me"}), [1, 2])
        self.assertIn("studentId=me", request.call_args.args[0])
        self.assertIn("pageToken=abc", request.call_args.args[0])

    def test_failed_course_retains_cache_other_course_deleted_and_deadline_updates(self):
        old = [work("a"), work("failed", course="2"), work("removed", course="3"), work("google", source="classroom")]
        new = work("a", due="2026-11-20T12:00:00+00:00")
        batch = Batch(items=[new], course_ids={"1", "2"}, failed_courses={"2"})
        merged = {item["id"]: item for item in merge_batch(old, "canvas", batch)}
        self.assertEqual(set(merged), {"a", "failed", "google"})
        self.assertEqual(merged["a"]["due_at"], new["due_at"])

    @patch("core.canvas_pages")
    def test_one_restricted_resource_category_does_not_hide_announcements(self, pages):
        pages.side_effect = [[{"id": 1, "title": "公告", "message": "要求"}], UserError("没有文件权限"), [], []]
        items, failed, warnings = canvas_resources("https://nu.instructure.com", "secret", {"id": "1"})
        self.assertEqual(items[0]["kind"], "announcement")
        self.assertEqual(failed, {"1:file"})
        self.assertTrue(warnings)
        old = [{"id": "file", "source": "canvas", "course_id": "1", "kind": "file"},
               {"id": "old", "source": "canvas", "course_id": "1", "kind": "announcement"}]
        batch = Batch(resources=items, failed_resources=failed)
        self.assertEqual({r["id"] for r in merge_resources(old, "canvas", batch)}, {"file", items[0]["id"]})

    def test_google_attachment_links(self):
        attachments = google_attachments({"materials": [{"driveFile": {"driveFile": {"title": "讲义", "alternateLink": "https://drive.google.com/file/d/1"}}}]})
        self.assertEqual(attachments[0]["title"], "讲义")

    def test_ics_utf8_folding_stable_ids_and_escape(self):
        item = work()
        item["description"] = "很长的日文日本語の講義資料" * 20
        data = export_ics([item, work("no-date", due=None)])
        lines = data.split(b"\r\n")
        self.assertTrue(all(len(line) <= 75 for line in lines))
        data.decode("utf-8")
        unfolded = data.replace(b"\r\n ", b"")
        self.assertIn(b"DTSTART:20261118T145900Z", unfolded)
        self.assertIn(b"UID:a@student-calendar.local", unfolded)
        self.assertIn(b"\\,", unfolded)
        self.assertIn(b"\\;", unfolded)
        self.assertEqual(unfolded.count(b"BEGIN:VEVENT"), 1)


class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.portal = Portal(Path(cls.temp.name), {})
        cls.server = make_server(cls.portal, port=0)
        cls.port = cls.server.server_address[1]
        cls.portal.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.portal.executor.shutdown(wait=True)
        cls.temp.cleanup()

    def request(self, path, cookie="", body=None, csrf="", origin=True, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if cookie:
            headers["Cookie"] = cookie
        if body is not None:
            headers.update({"Content-Type": "application/json", "X-CSRF-Token": csrf})
            if origin:
                headers["Origin"] = self.portal.base_url
        connection.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        data = response.read()
        result = (response.status, dict(response.headers), data)
        connection.close()
        return result

    def new_user(self, name):
        status, headers, data = self.request("/api/state")
        cookie = headers["Set-Cookie"].split(";")[0]
        csrf = json.loads(data)["csrf"]
        status, headers, data = self.request("/api/register", cookie, {"username": name, "password": "example-password"}, csrf)
        self.assertEqual(status, 200, data)
        cookie = headers["Set-Cookie"].split(";")[0]
        status, _, data = self.request("/api/state", cookie)
        return cookie, json.loads(data)

    def test_users_cannot_read_or_export_each_others_data(self):
        a_cookie, a = self.new_user("student-alpha")
        b_cookie, b = self.new_user("student-beta")
        self.portal.db.write(a["user"]["id"], "cache", dict(EMPTY, items=[work("private-alpha")]))
        self.portal.db.write(a["user"]["id"], "secrets", {"canvas": {"access_token": "secret-canary", "expires_at": 9e9}})
        status, _, data = self.request("/api/state", b_cookie)
        self.assertEqual(json.loads(data)["items"], [])
        self.assertNotIn(b"secret-canary", self.request("/api/state", a_cookie)[2])
        self.assertNotIn(b"private-alpha", self.request("/api/calendar.ics", b_cookie)[2])
        self.assertIn(b"private-alpha", self.request("/api/calendar.ics", a_cookie)[2])
        self.assertEqual(self.request("/api/calendar.ics")[0], 401)
        self.assertFalse(self.portal.db.login("student-alpha", "wrong-password"))

    def test_csrf_and_host_checks(self):
        cookie, account = self.new_user("student-gamma")
        self.assertEqual(self.request("/api/sync", cookie, {}, "wrong")[0], 403)
        self.assertEqual(self.request("/api/sync", cookie, {}, account["csrf"], origin=False)[0], 403)
        self.assertEqual(self.request("/api/state", host="evil.example")[0], 403)
        self.assertEqual(self.request("/data/portal.db", cookie)[0], 404)

    def test_server_cannot_share_another_server_port(self):
        with self.assertRaises(OSError):
            make_server(self.portal, port=self.port)

    def test_wrong_oauth_state_rejected(self):
        with self.assertRaises(UserError):
            self.portal.callback(1, "session", "canvas", {"state": ["invalid"], "code": ["canary"]})

    @patch("app.request_json")
    def test_pkce_binding_and_callback_cannot_switch_user(self, request):
        portal = Portal(Path(self.temp.name) / "oauth", {"classroom": {"client_id": "id", "client_secret": "secret"}})
        from urllib.parse import parse_qs, urlsplit
        params = parse_qs(urlsplit(portal.connect_url(1, "s1", "classroom")).query)
        self.assertEqual(params["code_challenge_method"], ["S256"])
        query = {"state": params["state"], "code": ["example"]}
        with self.assertRaises(UserError):
            portal.callback(2, "s1", "classroom", query)
        with self.assertRaises(UserError):
            portal.callback(1, "other-session", "classroom", query)
        request.assert_not_called()
        portal.executor.shutdown()

    @patch("app.fetch_canvas", side_effect=UserError("网络断开"))
    def test_failed_sync_preserves_snapshot(self, fetch):
        cookie, user = self.new_user("student-delta")
        uid = user["user"]["id"]
        self.portal.db.write(uid, "cache", dict(EMPTY, items=[work("keep-me")]))
        self.portal.db.write(uid, "secrets", {"canvas": {"access_token": "canary", "expires_at": 9e9}})
        self.portal.sync(uid)
        cache = self.portal.db.read(uid, "cache", EMPTY)
        self.assertEqual(cache["items"][0]["id"], "keep-me")
        self.assertEqual(cache["providers"]["canvas"]["state"], "error")

    def test_windows_secret_roundtrip(self):
        secret = b"private-test-token"
        encrypted = protect(secret)
        self.assertEqual(protect(encrypted, decrypt=True), secret)
        if sys.platform == "win32":
            self.assertNotIn(secret, encrypted)


if __name__ == "__main__":
    unittest.main()
