import http.client
import json
import unittest

import test_portal as portal_tests


class BrowserBridgeTests(unittest.TestCase):
    setUpClass = classmethod(portal_tests.PortalTests.setUpClass.__func__)
    tearDownClass = classmethod(portal_tests.PortalTests.tearDownClass.__func__)
    request = portal_tests.PortalTests.request
    new_user = portal_tests.PortalTests.new_user
    extension_origin = "chrome-extension://" + "a" * 32

    def extension(self, path, body=None, token="", origin=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Origin": origin or self.extension_origin, "X-Study-Dock-Extension": "a" * 32}
        if token:
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request("POST" if body is not None else "GET", path,
                           json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        result = response.status, dict(response.headers), json.loads(response.read())
        connection.close()
        return result

    def pair(self, name):
        cookie, user = self.new_user(name)
        status, _, data = self.request("/api/browser/pair-code", cookie, {}, user["csrf"])
        self.assertEqual(status, 200)
        code = json.loads(data)["code"]
        status, headers, result = self.extension("/api/extension/pair", {"code": code})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], self.extension_origin)
        return cookie, user, result["token"], code

    def binding(self, account="a" * 64):
        return {"source": "canvas", "origin": "https://nu.instructure.com", "account_hash": account, "label": "我的学校账号"}

    def snapshot(self):
        root = "https://nu.instructure.com/courses/17"
        return {"courses": [{"course_id": "17", "name": "电子回路", "url": root}],
                "items": [{"course_id": "17", "course": "电子回路", "title": "计算题", "url": root + "/assignments/21",
                    "description": "写出全部步骤。", "detail_level": 1, "due_at": "2026-11-20T23:59:00+09:00",
                    "status": "pending", "attachments": [{"title": "题目 PDF", "url": root + "/files/22"}]}],
                "resources": [{"course_id": "17", "kind": "page", "title": "讲义", "url": root + "/pages/notes", "description": "参考资料"}]}

    def test_one_time_pairing_and_import_into_only_paired_user(self):
        cookie, user, token, code = self.pair("browser-alpha")
        other_cookie, other = self.new_user("browser-beta")
        self.assertEqual(self.extension("/api/extension/pair", {"code": code})[0], 400)
        self.assertEqual(self.extension("/api/extension/bind", self.binding(), token)[0], 200)
        payload = dict(self.binding(), user_id=other["user"]["id"], snapshot=self.snapshot())
        self.assertEqual(self.extension("/api/extension/import", payload, token)[0], 200)
        state = json.loads(self.request("/api/state", cookie)[2])
        self.assertEqual(state["items"][0]["description"], "写出全部步骤。")
        self.assertEqual(state["items"][0]["due_at"], "2026-11-20T14:59:00+00:00")
        self.assertTrue(state["connections"]["canvas"]["connected"])
        self.assertEqual(state["connections"]["canvas"]["mode"], "browser")
        self.assertEqual(json.loads(self.request("/api/state", other_cookie)[2])["items"], [])
        self.assertNotIn(token, json.dumps(state))
        self.assertIn(b"DTSTART:20261120T145900Z", self.request("/api/calendar.ics", cookie)[2])

    def test_foreign_origin_and_cross_course_payload_rejected_atomically(self):
        cookie, user, token, _ = self.pair("browser-origin")
        self.extension("/api/extension/bind", self.binding(), token)
        snapshot = self.snapshot()
        snapshot["resources"][0]["url"] = "https://evil.example/courses/17/pages/notes"
        self.assertEqual(self.extension("/api/extension/import", dict(self.binding(), snapshot=snapshot), token)[0], 400)
        self.assertEqual(json.loads(self.request("/api/state", cookie)[2])["items"], [])
        self.assertEqual(self.extension("/api/extension/status", token=token, origin="https://evil.example")[0], 403)
        snapshot = self.snapshot()
        snapshot["items"][0]["course_id"] = "999"
        self.assertEqual(self.extension("/api/extension/import", dict(self.binding(), snapshot=snapshot), token)[0], 400)

    def test_account_switch_requires_binding_and_clears_old_platform(self):
        cookie, user, token, _ = self.pair("browser-switch")
        self.extension("/api/extension/bind", self.binding(), token)
        self.extension("/api/extension/import", dict(self.binding(), snapshot=self.snapshot()), token)
        switched = self.binding("b" * 64)
        self.assertEqual(self.extension("/api/extension/import", dict(switched, snapshot=self.snapshot()), token)[0], 400)
        self.assertEqual(self.extension("/api/extension/bind", switched, token)[0], 400)
        self.assertEqual(self.extension("/api/extension/bind", dict(switched, replace=True), token)[0], 200)
        self.assertEqual(json.loads(self.request("/api/state", cookie)[2])["items"], [])

    def test_incremental_snapshot_retains_unseen_records_and_rich_details(self):
        cookie, user, token, _ = self.pair("browser-incremental")
        self.extension("/api/extension/bind", self.binding(), token)
        self.extension("/api/extension/import", dict(self.binding(), snapshot=self.snapshot()), token)
        partial = self.snapshot()
        partial["items"][0].update(detail_level=0, description="", due_at=None)
        partial["resources"] = []
        self.extension("/api/extension/import", dict(self.binding(), snapshot=partial, warnings=["部分页面未加载"]), token)
        state = json.loads(self.request("/api/state", cookie)[2])
        self.assertEqual(state["items"][0]["description"], "写出全部步骤。")
        self.assertTrue(state["items"][0]["due_at"])
        self.assertEqual(len(state["resources"]), 1)
        self.assertEqual(state["providers"]["canvas"]["state"], "partial")

    def test_revocation_stops_old_plugin_and_request_is_acknowledged(self):
        cookie, user, token, _ = self.pair("browser-revoke")
        self.extension("/api/extension/bind", self.binding(), token)
        self.request("/api/browser/sync", cookie, {}, user["csrf"])
        request_id = self.extension("/api/extension/status", token=token)[2]["requests"]["canvas"]
        self.extension("/api/extension/import", dict(self.binding(), snapshot=self.snapshot(), request_id=request_id), token)
        self.assertEqual(self.extension("/api/extension/status", token=token)[2]["requests"], {})
        devices = json.loads(self.request("/api/state", cookie)[2])["browser"]["devices"]
        self.request("/api/browser/revoke", cookie, {"device_id": devices[0]["id"]}, user["csrf"])
        self.assertEqual(self.extension("/api/extension/status", token=token)[0], 401)


if __name__ == "__main__":
    unittest.main()
