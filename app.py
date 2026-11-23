"""A small multi-user learning portal; Python 3.11+, no external dependencies."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import io
from pathlib import Path
import re
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser
import zipfile

from core import (SCOPES, UserError, canvas_base, demo_items, export_ics, fetch_canvas,
                  fetch_classroom, merge_batch, merge_resources, now_iso, request_json)
from storage import Database
from browser_bridge import BrowserBridge
import study_assistant

ROOT = Path(__file__).resolve().parent
EMPTY = {"items": [], "courses": [], "resources": [], "providers": {}, "last_attempt_at": None}
CANVAS_SCOPES = ["url:GET|/api/v1/courses", "url:GET|/api/v1/courses/:course_id/assignments",
                 "url:GET|/api/v1/courses/:course_id/discussion_topics", "url:GET|/api/v1/courses/:course_id/files",
                 "url:GET|/api/v1/courses/:course_id/pages", "url:GET|/api/v1/courses/:course_id/modules",
                 "url:GET|/api/v1/courses/:course_id/modules/:module_id/items"]


class Portal:
    def __init__(self, directory: Path, config: dict):
        self.db = Database(directory / "portal.db")
        self.config = config
        self.base_url = config.get("base_url", "http://127.0.0.1:8840").rstrip("/")
        self.canvas = canvas_base(config.get("canvas", {}).get("base_url", "https://nu.instructure.com"))
        self.lock = threading.RLock()
        self.busy = set()
        self.pending = {}
        self.flashes = {}
        self.failures = {}
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.stop = threading.Event()
        self.browser = BrowserBridge(self)
        self.text_drafts = {}

    def assignment(self, uid, *, item_id=None, url=None):
        items = self.db.read(uid, "cache", EMPTY)["items"]
        return next((i for i in items if (item_id and i["id"] == item_id) or (url and i["url"] == url)), None)

    def save_text_draft(self, uid, item, text):
        if not item or not item.get("text_entry") or not isinstance(text, str) or not 0 < len(text.strip()) <= 12000:
            raise UserError("请核对文字作业，并输入 1 至 12000 字的草稿。")
        with self.lock:
            bindings = self.browser.info(uid)["bindings"]
            binding = bindings.get(item["source"])
            if not binding:
                raise UserError("文字提交需要当前浏览器已配对并绑定该平台。")
            self.text_drafts = {k: v for k, v in self.text_drafts.items() if v[0] > time.time()}
            self.text_drafts[(uid, item["url"])] = (time.time()+1800, binding["account_hash"], text)
        return {"ok": True}

    def browser_draft(self, uid, body):
        with self.lock:
            source, _ = self.browser.require_binding(uid, body)
            item = self.assignment(uid, url=body.get("url"))
            if not item or item["source"] != source or not item.get("text_entry"):
                raise UserError("这个学习账号没有同步到对应的文字作业。")
            key = (uid, item["url"])
            entry = self.text_drafts.get(key)
            if not entry or entry[0] < time.time() or entry[1] != body["account_hash"]:
                raise UserError("请先在学习空间的这项作业中确认草稿，然后回到原平台。")
            if body.get("consume") is True:
                del self.text_drafts[key]
        return {"text": entry[2], "title": item["title"]}

    def ready(self, source: str) -> bool:
        setting = self.config.get(source, {})
        return bool(setting.get("client_id") and setting.get("client_secret"))

    def state(self, user_id: int | None) -> dict:
        if user_id is None:
            return {"user": None}
        with self.lock:
            secret = self.db.read(user_id, "secrets", {})
            cache = self.db.read(user_id, "cache", EMPTY)
            connections = {source: {"configured": self.ready(source), "connected": bool(secret.get(source)),
                                     "status": cache["providers"].get(source)} for source in ("canvas", "classroom")}
            browser = self.browser.info(user_id)
            for source, binding in browser["bindings"].items():
                connections[source].update(connected=True, mode="browser", label=binding["label"])
            return dict(cache, user=self.db.user(user_id), connections=connections,
                        syncing=user_id in self.busy, canvas_url=self.canvas, browser=browser)

    def connect_url(self, user_id: int, session_id: str, source: str) -> str:
        if source not in ("canvas", "classroom"):
            raise UserError("未知平台。")
        if not self.ready(source):
            raise UserError("此平台尚未配置应用授权。请由应用管理员按 README 配置 OAuth 后再连接。")
        with self.lock:
            if user_id in self.busy:
                raise UserError("同步进行中，请稍后连接。")
            # Rebinding starts from an empty provider snapshot; tokens never cross users.
            self.pending = {key: value for key, value in self.pending.items() if time.time() - value["created"] < 600}
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
            self.pending[state] = {"user_id": user_id, "session_id": session_id, "source": source,
                                   "verifier": verifier, "created": time.time()}
        redirect = self.base_url + f"/oauth/{source}/callback"
        params = {"client_id": self.config[source]["client_id"], "redirect_uri": redirect,
                  "response_type": "code", "state": state}
        if source == "canvas":
            params["scope"] = " ".join(CANVAS_SCOPES)
            return self.canvas + "/login/oauth2/auth?" + urlencode(params)
        params.update(scope=" ".join(SCOPES), access_type="offline", prompt="consent select_account",
                      code_challenge_method="S256", code_challenge=base64.urlsafe_b64encode(
                          hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode())
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

    def callback(self, user_id: int, session_id: str, source: str, query: dict):
        with self.lock:
            state = query.get("state", [""])[0]
            pending = self.pending.get(state)
            if (not pending or pending["user_id"] != user_id or pending["session_id"] != session_id
                    or pending["source"] != source or time.time() - pending["created"] >= 600):
                raise UserError("登录授权已过期或不属于当前账号，请重新连接。")
            self.pending.pop(state)
            if query.get("error") or not query.get("code"):
                raise UserError("你取消了授权，或学校未允许此应用。")
            if user_id in self.busy:
                raise UserError("同步进行中，请稍后重新连接。")
            setting = self.config[source]
            form = {"client_id": setting["client_id"], "client_secret": setting["client_secret"],
                    "redirect_uri": self.base_url + f"/oauth/{source}/callback",
                    "grant_type": "authorization_code", "code": query["code"][0]}
            endpoint = self.canvas + "/login/oauth2/token"
            if source == "classroom":
                endpoint = "https://oauth2.googleapis.com/token"
                form["code_verifier"] = pending["verifier"]
            token, _ = request_json(endpoint, form=form)
            if not token.get("access_token") or not token.get("refresh_token"):
                raise UserError("平台没有返回可持续使用的授权，请重新连接并同意离线访问。")
            if source == "classroom" and not set(SCOPES).issubset(set(token.get("scope", "").split())):
                raise UserError("请同意课程、作业、公告和资料的只读权限后再连接。")
            token["expires_at"] = time.time() + token.get("expires_in", 3600)
            secret = self.db.read(user_id, "secrets", {})
            secret[source] = token
            self.db.write(user_id, "secrets", secret)
            browser = self.db.read(user_id, "browser", {"bindings": {}, "requests": {}})
            browser["bindings"].pop(source, None)
            browser["requests"].pop(source, None)
            self.db.write(user_id, "browser", browser)
            self.clear_cache(user_id, source)
        self.schedule(user_id)

    def access_token(self, user_id: int, source: str) -> str:
        with self.lock:
            secret = self.db.read(user_id, "secrets", {})
            token = secret.get(source)
            if not token:
                raise UserError("请先连接这个平台。")
            if token.get("expires_at", 0) <= time.time() + 60:
                setting = self.config.get(source, {})
                form = {"client_id": setting.get("client_id", ""), "client_secret": setting.get("client_secret", ""),
                        "grant_type": "refresh_token", "refresh_token": token["refresh_token"]}
                endpoint = self.canvas + "/login/oauth2/token" if source == "canvas" else "https://oauth2.googleapis.com/token"
                refreshed, _ = request_json(endpoint, form=form)
                if not refreshed.get("access_token"):
                    raise UserError("平台没有返回有效授权，请重新连接。")
                token.update(refreshed)
                token["expires_at"] = time.time() + refreshed.get("expires_in", 3600)
                self.db.write(user_id, "secrets", secret)
            return token["access_token"]

    def clear_cache(self, user_id: int, source: str):
        cache = self.db.read(user_id, "cache", EMPTY)
        for key in ("items", "courses", "resources"):
            cache[key] = [item for item in cache[key] if item["source"] != source]
        cache["providers"].pop(source, None)
        self.db.write(user_id, "cache", cache)

    def disconnect(self, user_id: int, source: str):
        if source not in ("canvas", "classroom"):
            raise UserError("未知平台。")
        with self.lock:
            if user_id in self.busy:
                raise UserError("同步进行中，请稍后解除连接。")
            self.pending = {key: value for key, value in self.pending.items()
                            if not (value["user_id"] == user_id and value["source"] == source)}
            secret = self.db.read(user_id, "secrets", {})
            secret.pop(source, None)
            self.db.write(user_id, "secrets", secret)
            browser = self.db.read(user_id, "browser", {"bindings": {}, "requests": {}})
            browser["bindings"].pop(source, None)
            browser["requests"].pop(source, None)
            self.db.write(user_id, "browser", browser)
            self.clear_cache(user_id, source)

    def schedule(self, user_id: int) -> bool:
        with self.lock:
            if user_id in self.busy or not self.db.read(user_id, "secrets", {}):
                return False
            self.busy.add(user_id)
        self.executor.submit(self.sync, user_id)
        return True

    def sync(self, user_id: int):
        try:
            cache = self.db.read(user_id, "cache", EMPTY)
            cache["last_attempt_at"] = now_iso()
            secret = self.db.read(user_id, "secrets", {})
            for source in ("canvas", "classroom"):
                if not secret.get(source):
                    continue
                old = cache["providers"].get(source, {})
                try:
                    token = self.access_token(user_id, source)
                    batch = fetch_canvas(self.canvas, token) if source == "canvas" else fetch_classroom(token)
                    cache["items"] = merge_batch(cache["items"], source, batch)
                    cache["courses"] = [c for c in cache["courses"] if c["source"] != source] + batch.courses
                    cache["resources"] = merge_resources(cache["resources"], source, batch)
                    cache["providers"][source] = {
                        "state": "partial" if batch.warnings else "ok", "attempted_at": now_iso(),
                        "last_success_at": old.get("last_success_at") if batch.warnings else now_iso(),
                        "warnings": batch.warnings, "message": "部分内容未更新，保留已有缓存。" if batch.warnings else "同步成功"}
                except Exception as error:
                    cache["providers"][source] = {"state": "error", "attempted_at": now_iso(),
                        "last_success_at": old.get("last_success_at"), "warnings": [],
                        "message": str(error) if isinstance(error, UserError) else "同步失败；已有缓存已保留，请稍后重试。"}
            self.db.write(user_id, "cache", cache)
        finally:
            with self.lock:
                self.busy.discard(user_id)

    def auto_sync(self):
        while not self.stop.wait(30):
            for user_id in self.db.connected_users():
                cache = self.db.read(user_id, "cache", EMPTY)
                from datetime import datetime
                last = cache.get("last_attempt_at")
                age = time.time() - datetime.fromisoformat(last).timestamp() if last else 901
                if age >= 900:
                    self.schedule(user_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "StudyPortal"

    @property
    def app(self) -> Portal:
        return self.server.portal

    def log_message(self, format, *args):
        # OAuth callback query strings contain credentials. Never log request targets.
        pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionError, TimeoutError):
            # Closing or refreshing a tab can abort an otherwise valid response.
            pass

    def reject_request(self, message, status=403):
        # Drain a small rejected POST body before closing. An unread body can cause
        # a TCP reset on Windows before the client receives the error response.
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if 0 < length <= 16384:
                self.connection.settimeout(2)
                self.rfile.read(length)
        except (ValueError, OSError):
            pass
        return self.json({"error": message}, status)

    def send(self, data: bytes, status=200, content_type="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if getattr(self, "extension_origin", None):
            self.send_header("Access-Control-Allow-Origin", self.extension_origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        if getattr(self, "new_cookie", None):
            secure = "; Secure" if self.app.base_url.startswith("https://") else ""
            self.send_header("Set-Cookie", f"study_session={self.new_cookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800{secure}")
        self.end_headers()
        self.wfile.write(data)

    def json(self, value, status=200):
        self.send(json.dumps(value, ensure_ascii=False).encode(), status)

    def session(self) -> dict:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            entry = cookie.get("study_session")
            session = self.app.db.session(entry.value) if entry else None
        except Exception:
            session = None
        if not session:
            self.new_cookie, session = self.app.db.new_session()
        return session

    def valid_host(self):
        return self.headers.get("Host", "").lower() == urlsplit(self.app.base_url).netloc.lower()

    def extension_source(self):
        origin = self.headers.get("Origin", "")
        identifier = self.headers.get("X-Study-Dock-Extension", "")
        if not origin and re.fullmatch(r"[a-p]{32}", identifier):
            origin = "chrome-extension://" + identifier
        if not re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
            return None
        if identifier and origin != "chrome-extension://" + identifier:
            return None
        return origin

    def do_OPTIONS(self):
        self.new_cookie = None
        self.extension_origin = self.extension_source()
        if not self.valid_host() or not self.extension_origin or not self.path.startswith("/api/extension/"):
            return self.json({"error": "不允许这个来源。"}, 403)
        self.send(b"", 204, extra={"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Study-Dock-Extension",
            "Access-Control-Allow-Private-Network": "true"})

    def extension_request(self, path, post=False):
        self.extension_origin = self.extension_source()
        if not self.extension_origin:
            return self.reject_request("请使用配对的浏览器插件。") if post else self.json({"error": "请使用配对的浏览器插件。"}, 403)
        try:
            body = {}
            if post:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4 * 1024 * 1024 or self.headers.get_content_type() != "application/json":
                    raise UserError("采集请求过大或格式不正确。")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise UserError("采集请求格式不正确。")
            if path == "/api/extension/pair" and post:
                code = body.get("code", "")
                if not isinstance(code, str) or not 16 <= len(code) <= 100:
                    raise UserError("请填写网页生成的一次性配对码。")
                token, uid = self.app.db.pair_extension(code, self.extension_origin)
                return self.json({"token": token, "user": self.app.db.user(uid), "canvas_url": self.app.canvas})
            authorization = self.headers.get("Authorization", "")
            token = authorization[7:] if authorization.startswith("Bearer ") else ""
            device = self.app.db.extension_device(token, self.extension_origin) if token else None
            if not device:
                return self.json({"error": "插件配对已失效，请重新配对。"}, 401)
            uid = device["user_id"]
            if path == "/api/extension/status" and not post:
                return self.json(dict(self.app.browser.info(uid), user=self.app.db.user(uid)))
            actions = {"/api/extension/bind": self.app.browser.bind,
                       "/api/extension/import": self.app.browser.import_data,
                       "/api/extension/report": self.app.browser.report,
                       "/api/extension/text-draft": self.app.browser_draft}
            if post and path in actions:
                return self.json(actions[path](uid, body))
            return self.json({"error": "未知插件操作。"}, 404)
        except (ValueError, UserError) as error:
            return self.json({"error": str(error) if isinstance(error, UserError) or not isinstance(error, json.JSONDecodeError) else "采集请求格式不正确。"}, 400)
        except Exception:
            return self.json({"error": "采集导入失败，已有数据保留。"}, 500)

    def do_GET(self):
        self.new_cookie = None
        if not self.valid_host():
            return self.json({"error": "无效的访问地址。"}, 403)
        path = urlsplit(self.path).path
        if path.startswith("/api/extension/"):
            return self.extension_request(path)
        try:
            if path == "/api/health":
                return self.json({"app": "study-dock", "version": "0.3.0", "browser_collector": True})
            if path in ("/", "/app.js", "/browser.js", "/assistant.js", "/style.css"):
                filename = "index.html" if path == "/" else path[1:]
                types = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
                         "browser.js": "text/javascript; charset=utf-8", "assistant.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}
                return self.send((ROOT / "static" / filename).read_bytes(), content_type=types[filename])
            if path == "/extension.zip":
                output = io.BytesIO()
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                    for file in (ROOT / "extension").iterdir():
                        if file.is_file() and file.suffix in (".json", ".js", ".html", ".css", ".md"):
                            archive.write(file, "study-dock-extension/" + file.name)
                return self.send(output.getvalue(), content_type="application/zip",
                                 extra={"Content-Disposition": 'attachment; filename="study-dock-extension.zip"'})
            if path == "/api/demo":
                items = demo_items()
                courses = [{"id": f"{i['source']}:{i['course_id']}", "course_id": i["course_id"],
                            "name": i["course"], "source": i["source"], "url": ""} for i in items]
                resources = [{"id": f"demo:resource:{i['course_id']}", "course_id": i["course_id"],
                              "source": i["source"], "kind": "material", "title": "第 6 回讲义与参考资料",
                              "description": "这里会展示老师发布的资料说明。真实资料在连接账号后读取。",
                              "group": "", "attachments": [], "url": "", "updated_at": None} for i in items]
                return self.json(dict(EMPTY, user={"name": "演示账号"}, demo=True, items=items,
                                      courses=courses, resources=resources, syncing=False, connections={}))
            session = self.session()
            user_id = session["user_id"]
            if path == "/api/state":
                state = self.app.state(user_id)
                state["csrf"] = session["csrf"]
                state["flash"] = self.app.flashes.pop(session["id"], "")
                return self.json(state)
            if user_id is None:
                return self.json({"error": "请先登录。"}, 401)
            if path == "/api/calendar.ics":
                data = export_ics(self.app.db.read(user_id, "cache", EMPTY)["items"])
                return self.send(data, content_type="text/calendar; charset=utf-8",
                                 extra={"Content-Disposition": 'attachment; filename="assignments.ics"'})
            if path in ("/oauth/canvas/callback", "/oauth/classroom/callback"):
                source = path.split("/")[2]
                try:
                    self.app.callback(user_id, session["id"], source, parse_qs(urlsplit(self.path).query))
                    self.app.flashes[session["id"]] = "连接成功，正在读取你的课程。"
                except UserError as error:
                    self.app.flashes[session["id"]] = str(error)
                return self.send(b"", 303, extra={"Location": "/#connections"})
            return self.json({"error": "找不到这个页面。"}, 404)
        except Exception:
            return self.json({"error": "读取失败，请稍后重试；如授权文件来自其他 Windows 账号，请重新授权。"}, 500)

    def do_POST(self):
        self.new_cookie = None
        path = urlsplit(self.path).path
        if self.valid_host() and path.startswith("/api/extension/"):
            return self.extension_request(path, post=True)
        if not self.valid_host() or self.headers.get("Origin") != self.app.base_url:
            return self.reject_request("请求来源不匹配。")
        session = self.session()
        if not hmac.compare_digest(self.headers.get("X-CSRF-Token", "").encode(), session["csrf"].encode()):
            return self.reject_request("页面已过期，请刷新后重试。")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            max_length = 96_000 if path in ("/api/assistant/ask", "/api/assistant/save-draft") else 16_384
            if not 0 <= length <= max_length or self.headers.get_content_type() != "application/json":
                raise UserError("请求格式不正确。")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise UserError("请求格式不正确。")
            path = urlsplit(self.path).path
            if path in ("/api/login", "/api/register"):
                username, password = body.get("username", ""), body.get("password", "")
                if not isinstance(username, str) or not isinstance(password, str) or len(username) > 80 or len(password) > 1024:
                    raise UserError("用户名或密码格式不正确。")
                key = self.client_address[0]
                attempts = [t for t in self.app.failures.get(key, []) if time.time() - t < 300]
                if len(attempts) >= 10:
                    return self.json({"error": "尝试次数过多，请 5 分钟后再试。"}, 429)
                self.app.failures[key] = attempts + [time.time()]
                user_id = (self.app.db.register(username, password) if path.endswith("register")
                           else self.app.db.login(username, password))
                if user_id is None:
                    return self.json({"error": "用户名或密码不正确。"}, 400)
                self.app.db.delete_session(session["id"])
                self.new_cookie, session = self.app.db.new_session(user_id)
                self.app.failures.pop(key, None)
                self.app.schedule(user_id)
                return self.json({"ok": True})
            if session["user_id"] is None:
                return self.json({"error": "请先登录。"}, 401)
            user_id = session["user_id"]
            if path == "/api/assistant/ask":
                return self.json(study_assistant.ask(ROOT, self.app.db.read(user_id, "cache", EMPTY), body))
            if path in ("/api/assistant/draft", "/api/assistant/save-draft"):
                item = self.app.assignment(user_id, item_id=body.get("id"))
                if path.endswith("/save-draft"):
                    return self.json(self.app.save_text_draft(user_id, item, body.get("text")))
                return self.json({"text": study_assistant.draft(ROOT, item)})
            if path == "/api/browser/pair-code":
                return self.json({"code": self.app.db.pairing_code(user_id), "expires_in": 600})
            if path == "/api/browser/revoke":
                device_id = body.get("device_id", "")
                if not isinstance(device_id, str):
                    raise UserError("设备标识不正确。")
                self.app.db.revoke_extension(user_id, device_id)
                return self.json({"ok": True})
            if path == "/api/browser/sync":
                return self.json({"queued": self.app.browser.request_sync(user_id)})
            if path == "/api/logout":
                self.app.db.delete_session(session["id"])
                self.new_cookie, _ = self.app.db.new_session()
                return self.json({"ok": True})
            if path == "/api/sync":
                return self.json({"started": self.app.schedule(user_id)})
            if path == "/api/connect":
                return self.json({"url": self.app.connect_url(user_id, session["id"], body.get("source", ""))})
            if path == "/api/disconnect":
                self.app.disconnect(user_id, body.get("source", ""))
                return self.json({"ok": True})
            return self.json({"error": "找不到这个操作。"}, 404)
        except (ValueError, UserError) as error:
            return self.json({"error": str(error) if not isinstance(error, json.JSONDecodeError) else "请求格式不正确。"}, 400)
        except Exception:
            return self.json({"error": "操作失败，请稍后重试。"}, 500)


class PortalHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        # Windows SO_REUSEADDR can bind a port already owned by another application.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(portal: Portal, host="127.0.0.1", port=8840):
    server = PortalHTTPServer((host, port), Handler)
    server.portal = portal
    return server


def main():
    parser = argparse.ArgumentParser(description="多用户学生学习门户")
    parser.add_argument("--port", type=int, default=8840)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    config_path = ROOT / "app_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
    config.setdefault("base_url", f"http://127.0.0.1:{args.port}")
    url = urlsplit(config["base_url"])
    if args.host != "127.0.0.1" and url.scheme != "https":
        parser.error("对外提供服务时请先在 app_config.json 设置 HTTPS base_url 并配置反向代理。")
    portal = Portal(ROOT / "data", config)
    server = make_server(portal, args.host, args.port)
    threading.Thread(target=portal.auto_sync, daemon=True).start()
    print(f"Study Portal: {portal.base_url}\nPress Ctrl+C to stop.", flush=True)
    if args.open:
        webbrowser.open(portal.base_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        portal.stop.set()
        server.server_close()
        portal.executor.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    main()
