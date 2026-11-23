"""Per-user pairing and validated, incremental imports from the browser collector."""
from datetime import datetime
import hashlib
import json
import re
import time
from urllib.parse import urlsplit

from core import UserError, now_iso, parse_time, safe_url


class BrowserBridge:
    def __init__(self, portal):
        self.portal = portal
        self.db = portal.db

    def info(self, uid):
        document = self.db.read(uid, "browser", {"bindings": {}, "requests": {}})
        return dict(document, devices=self.db.extension_devices(uid))

    def bind(self, uid, body):
        source, account = self.validate_binding(body)
        with self.portal.lock:
            if uid in self.portal.busy:
                raise UserError("接口同步进行中，请稍后绑定浏览器账号。")
            document = self.db.read(uid, "browser", {"bindings": {}, "requests": {}})
            previous = document["bindings"].get(source)
            if previous and previous["account_hash"] != account and not body.get("replace"):
                raise UserError("浏览器账号发生变化，请主动重新绑定后再同步。")
            if not previous or previous["account_hash"] != account:
                self.portal.clear_cache(uid, source)
            secret = self.db.read(uid, "secrets", {})
            secret.pop(source, None)
            self.db.write(uid, "secrets", secret)
            document["bindings"][source] = {"account_hash": account, "label": self.text(body.get("label"), 160),
                "origin": self.origin(source), "bound_at": now_iso(), "mode": "browser"}
            document["requests"].pop(source, None)
            self.db.write(uid, "browser", document)
        return {"ok": True}

    def origin(self, source):
        return self.portal.canvas if source == "canvas" else "https://classroom.google.com"

    def validate_binding(self, body):
        source, account = body.get("source"), body.get("account_hash", "")
        if source not in ("canvas", "classroom") or not isinstance(account, str) or not re.fullmatch(r"[a-f0-9]{64}", account):
            raise UserError("平台或账号标识不正确。")
        if body.get("origin") != self.origin(source):
            raise UserError("采集来源不是已配置的学校平台。")
        return source, account

    def require_binding(self, uid, body):
        source, account = self.validate_binding(body)
        document = self.db.read(uid, "browser", {"bindings": {}, "requests": {}})
        binding = document["bindings"].get(source)
        if not binding or binding["account_hash"] != account:
            raise UserError("网页账号与当前绑定不一致，请重新绑定。")
        return source, document

    @staticmethod
    def text(value, limit):
        if value is None:
            return ""
        if not isinstance(value, str):
            raise UserError("采集文字格式不正确。")
        return value[:limit]

    def record(self, source, raw, kind):
        if not isinstance(raw, dict):
            raise UserError("采集记录格式不正确。")
        course_id = raw.get("course_id", "")
        if not isinstance(course_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", course_id):
            raise UserError("课程标识不正确。")
        url = safe_url(raw.get("url", ""))
        parsed = urlsplit(url)
        if f"{parsed.scheme}://{parsed.netloc}" != self.origin(source):
            raise UserError("课程或作业地址不属于所选平台。")
        path = parsed.path
        if source == "canvas":
            valid = re.match(r"^/courses/" + re.escape(course_id) + r"(?:/|$)", path)
        else:
            valid = re.match(r"^/(?:u/\d+/)?c/" + re.escape(course_id) + r"(?:/|$)", path)
        if not valid:
            raise UserError("采集地址与课程不匹配。")
        if kind == "courses":
            return {"id": f"{source}:{course_id}", "course_id": course_id, "source": source,
                    "name": self.text(raw.get("name"), 300) or "未命名课程", "url": url}
        ident = "browser:" + source + ":" + hashlib.sha256(url.encode()).hexdigest()[:32]
        attachments = raw.get("attachments", [])
        if not isinstance(attachments, list) or len(attachments) > 100:
            raise UserError("附件数量或格式不正确。")
        clean = {"id": ident, "source": source, "course_id": course_id, "url": url,
                 "title": self.text(raw.get("title"), 3000) or "未命名内容",
                 "description": self.text(raw.get("description"), 30000), "updated_at": None,
                 "observed_at": now_iso(), "collection_mode": "browser",
                 "detail_level": raw.get("detail_level") if raw.get("detail_level") in (1, 2) else 0,
                 "attachments": [{"title": self.text(a.get("title"), 500) or "查看附件", "url": safe_url(a.get("url", ""))}
                                 for a in attachments if isinstance(a, dict) and safe_url(a.get("url", ""))]}
        if kind == "items":
            try:
                due = parse_time(raw.get("due_at"))
            except (ValueError, TypeError, AttributeError):
                raise UserError("截止日期格式不正确，已有缓存未修改。") from None
            status = raw.get("status", "unknown")
            clean.update(course=self.text(raw.get("course"), 300), due_at=due.isoformat() if due else None,
                         due_text=self.text(raw.get("due_text"), 500),
                         date_uncertain=bool(raw.get("date_uncertain")), text_entry=raw.get("text_entry") is True,
                         status=status if status in ("pending", "submitted", "returned", "graded", "excused") else "unknown")
        else:
            category = raw.get("kind", "material")
            clean.update(kind=category if category in ("announcement", "file", "page", "module", "material") else "material",
                         group=self.text(raw.get("group"), 300))
        return clean

    def import_data(self, uid, body):
        with self.portal.lock:
            source, document = self.require_binding(uid, body)
            if uid in self.portal.busy:
                raise UserError("接口同步进行中，请稍后重试。")
            snapshot = body.get("snapshot", {})
            if not isinstance(snapshot, dict):
                raise UserError("采集数据格式不正确。")
            records = {}
            for key, limit in (("courses", 200), ("items", 2000), ("resources", 5000)):
                values = snapshot.get(key, [])
                if not isinstance(values, list) or len(values) > limit:
                    raise UserError("采集数据过多，请分批同步。")
                records[key] = [self.record(source, raw, key) for raw in values]
            cache = self.db.read(uid, "cache", {"items": [], "courses": [], "resources": [], "providers": {}, "last_attempt_at": None})
            for key, values in records.items():
                merged = {r["id"]: r for r in cache[key]}
                for value in values:
                    old = merged.get(value["id"])
                    if old and old.get("detail_level", 0) > value.get("detail_level", 0):
                        value = dict(old, observed_at=value["observed_at"])
                    merged[value["id"]] = value
                cache[key] = list(merged.values())
            warnings = body.get("warnings", [])
            if not isinstance(warnings, list):
                raise UserError("采集状态格式不正确。")
            warnings = [self.text(v, 500) for v in warnings[:30]]
            cache["providers"][source] = {"mode": "browser", "state": "partial" if warnings else "ok",
                "attempted_at": now_iso(), "last_success_at": now_iso(), "warnings": warnings,
                "message": "已更新本次读到的页面；浏览器采集按已访问内容增量合并，不代表平台全部内容。"}
            cache["last_attempt_at"] = now_iso()
            self.db.write(uid, "cache", cache)
            diagnostics=body.get("diagnostics")
            if isinstance(diagnostics,dict) and len(json.dumps(diagnostics).encode())<500000:
                latest=self.db.read(uid,"browser_diagnostics",{})
                latest[source]=dict(diagnostics,imported_at=now_iso())
                self.db.write(uid,"browser_diagnostics",latest)
            document["bindings"][source]["last_import_at"] = now_iso()
            request_id = body.get("request_id")
            if request_id and document["requests"].get(source) == request_id:
                document["requests"].pop(source, None)
            self.db.write(uid, "browser", document)
            return {"ok": True, "counts": {key: len(value) for key, value in records.items()}}

    def report(self, uid, body):
        with self.portal.lock:
            source, document = self.require_binding(uid, body)
            cache = self.db.read(uid, "cache", {"items": [], "courses": [], "resources": [], "providers": {}, "last_attempt_at": None})
            old = cache["providers"].get(source, {})
            cache["providers"][source] = dict(old, mode="browser", state="error", attempted_at=now_iso(),
                message=self.text(body.get("message"), 500) or "页面未能读取，已有缓存保留。")
            self.db.write(uid, "cache", cache)
            if body.get("request_id") == document["requests"].get(source):
                document["requests"].pop(source, None)
                self.db.write(uid, "browser", document)
            return {"ok": True}

    def request_sync(self, uid):
        with self.portal.lock:
            document = self.db.read(uid, "browser", {"bindings": {}, "requests": {}})
            for source in document["bindings"]:
                document["requests"][source] = str(time.time_ns())
            self.db.write(uid, "browser", document)
            return bool(document["bindings"])
