"""Read-only Canvas / Google Classroom clients and calendar normalization."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

UTC = timezone.utc
JST = timezone(timedelta(hours=9), "Asia/Tokyo")
SCOPES = ["https://www.googleapis.com/auth/classroom.courses.readonly",
          "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
          "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
          "https://www.googleapis.com/auth/classroom.announcements.readonly"]


class UserError(Exception):
    """A safe, actionable error; never contains a response body or credential."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("截止时间必须包含时区")
    return parsed.astimezone(UTC)


def safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value or "")
        return value if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username else ""
    except ValueError:
        return ""


def canvas_base(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, 443)
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError()
    except ValueError:
        raise UserError("Canvas 地址请填写 HTTPS 首页，例如 https://nu.instructure.com/") from None
    return f"https://{parsed.hostname}"


class TextExtractor(HTMLParser):
    def __init__(self, base_url: str = ""):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
        self.links = []
        self.base_url = base_url
        self.active_link = None
        self.link_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a" and not self.hidden:
            attributes = dict(attrs)
            href = (attributes.get("href") or "").strip()
            resolved = urljoin(self.base_url, href)
            self.active_link = None
            self.link_text = []
            if href and not href.startswith("#") and safe_url(resolved):
                self.active_link = {"title": attributes.get("title") or "查看附件或链接", "url": resolved}
                self.links.append(self.active_link)
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "div", "br", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "a" and self.active_link is not None:
            title = "".join(self.link_text).strip()
            if title:
                self.active_link["title"] = title
            self.active_link = None
            self.link_text = []
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
            if self.active_link is not None:
                self.link_text.append(data)


def plain_html(value: str) -> str:
    parser = TextExtractor()
    parser.feed(value or "")
    return "".join(parser.parts).strip()


def html_links(value: str, base_url: str = "") -> list:
    parser = TextExtractor(base_url)
    parser.feed(value or "")
    return parser.links


def google_attachments(raw: dict) -> list:
    attachments = []
    for material in raw.get("materials", []):
        item = material.get("driveFile", {}).get("driveFile") or material.get("link") or material.get(
            "youtubeVideo") or material.get("form") or {}
        url = safe_url(item.get("alternateLink") or item.get("url") or item.get("formUrl") or "")
        if url:
            attachments.append({"title": item.get("title", "查看附件"), "url": url})
    return attachments


class NoRedirect(HTTPRedirectHandler):
    # In particular, do not forward a bearer token to an SSO redirect.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url: str, token: str = "", form: dict | None = None) -> tuple:
    headers = {"Accept": "application/json", "User-Agent": "StudentCalendar/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urlencode(form).encode()
    opener = build_opener(NoRedirect)
    for attempt in range(3):
        try:
            with opener.open(Request(url, data=data, headers=headers), timeout=25) as response:
                return json.load(response), response.headers
        except HTTPError as error:
            code = error.code
            retry_after = error.headers.get("Retry-After", "")
            error.close()
            if (code == 429 or 500 <= code <= 599) and attempt < 2:
                delay = min(8, int(retry_after)) if retry_after.isdigit() else 2 ** attempt
                time.sleep(delay)
                continue
            if code == 401:
                message = "授权已过期，请重新连接账号。"
            elif code == 403:
                message = "账号或学校未允许此接口访问，请检查授权或联系学校管理员。"
            elif code == 429:
                message = "平台请求过于频繁，请稍后同步。"
            elif 300 <= code < 400:
                message = "接口被重定向，请确认 Canvas 地址和 API 授权。"
            elif code == 400 and form is not None:
                message = "Google 授权失效或配置不匹配，请重新连接。"
            else:
                message = f"平台返回 HTTP {code}，请稍后重试。"
            raise UserError(message) from None
        except (URLError, TimeoutError, OSError):
            raise UserError("暂时无法连接平台，请检查网络；上次缓存会保留。") from None
        except (ValueError, UnicodeError):
            raise UserError("平台返回的内容不是有效 JSON，请检查接口地址。") from None
    raise UserError("平台暂时不可用。")


def canvas_pages(url: str, token: str) -> list:
    origin = urlsplit(url)
    expected = (origin.scheme, origin.netloc)
    seen = set()
    items = []
    while url:
        current = urlsplit(url)
        if (current.scheme, current.netloc) != expected or current.username or url in seen:
            raise UserError("Canvas 分页链接异常，已停止同步。")
        seen.add(url)
        page, headers = request_json(url, token)
        if not isinstance(page, list):
            raise UserError("Canvas 数据格式异常。")
        items.extend(page)
        links = re.findall(r'<([^>]+)>\s*;\s*rel="([^"]+)"', headers.get("Link", ""))
        url = next((urljoin(url, link) for link, rel in links if rel == "next"), "")
    return items


def google_pages(url: str, token: str, key: str, params: dict | None = None) -> list:
    params = dict(params or {}, pageSize=100)
    items, seen = [], set()
    while True:
        page, _ = request_json(url + "?" + urlencode(params), token)
        items.extend(page.get(key, []))
        next_page = page.get("nextPageToken")
        if not next_page:
            return items
        if next_page in seen:
            raise UserError("Classroom 分页链接异常，已停止同步。")
        seen.add(next_page)
        params["pageToken"] = next_page


def canvas_assignment(base: str, course: dict, raw: dict) -> dict:
    submission = raw.get("submission") or {}
    state = submission.get("workflow_state", "")
    if submission.get("excused"):
        status = "excused"
    elif state in ("submitted", "pending_review"):
        status = "submitted"
    elif state == "graded" and submission.get("submitted_at"):
        status = "submitted"
    elif state == "graded":
        status = "graded"
    elif state in ("unsubmitted", "ungraded"):
        status = "pending"
    else:
        status = "unknown"
    due = parse_time(raw.get("due_at"))
    course_id = str(course["id"])
    return {"id": f"canvas:{urlsplit(base).netloc}:{course_id}:{raw['id']}",
            "source": "canvas", "course_id": course_id, "course": course.get("name", course_id),
            "title": raw.get("name", "未命名作业"), "description": plain_html(raw.get("description")),
            "due_at": due.isoformat() if due else None, "status": status,
            "text_entry": "online_text_entry" in (raw.get("submission_types") or []),
            "attachments": html_links(raw.get("description"), base + f"/courses/{course_id}/assignments/{raw['id']}"),
            "url": safe_url(raw.get("html_url", "")), "updated_at": raw.get("updated_at")}


def classroom_assignment(course: dict, raw: dict, submission: dict | None) -> dict:
    due = None
    if raw.get("dueDate"):
        date = raw["dueDate"]
        clock = raw.get("dueTime")
        if clock is None:
            clock = {"hours": 23, "minutes": 59}
        due = datetime(date["year"], date["month"], date["day"], clock.get("hours", 0),
                       clock.get("minutes", 0), clock.get("seconds", 0), tzinfo=UTC)
    state = (submission or {}).get("state", "")
    status = {"TURNED_IN": "submitted", "RETURNED": "returned", "NEW": "pending",
              "CREATED": "pending", "RECLAIMED_BY_STUDENT": "pending"}.get(state, "unknown")
    course_id = str(course["id"])
    return {"id": f"classroom:{course_id}:{raw['id']}", "source": "classroom",
            "text_entry": raw.get("workType") == "SHORT_ANSWER_QUESTION",
            "course_id": course_id, "course": course.get("name", course_id),
            "title": raw.get("title", "未命名作业"), "description": raw.get("description", ""),
            "due_at": due.isoformat() if due else None, "status": status,
            "attachments": google_attachments(raw),
            "url": safe_url(raw.get("alternateLink", "")), "updated_at": raw.get("updateTime")}


@dataclass
class Batch:
    items: list = field(default_factory=list)
    course_ids: set = field(default_factory=set)
    failed_courses: set = field(default_factory=set)
    warnings: list = field(default_factory=list)
    courses: list = field(default_factory=list)
    resources: list = field(default_factory=list)
    failed_resources: set = field(default_factory=set)


def course_record(source: str, course: dict, url: str) -> dict:
    return {"id": f"{source}:{course['id']}", "course_id": str(course["id"]), "source": source,
            "name": course.get("name", "未命名课程"), "url": safe_url(url)}


def canvas_resources(base: str, token: str, course: dict) -> tuple:
    root = base + f"/api/v1/courses/{course['id']}"
    records, failed, warnings = [], set(), []
    groups = [("announcement", "/discussion_topics?only_announcements=true&per_page=100"),
              ("file", "/files?per_page=100"), ("page", "/pages?per_page=100"),
              ("module", "/modules?include[]=items&per_page=100")]
    for kind, path in groups:
        try:
            normalized = []
            for raw in canvas_pages(root + path, token):
                if kind == "module":
                    children = raw.get("items")
                    if children is None or len(children) < raw.get("items_count", 0):
                        children = canvas_pages(root + f"/modules/{raw['id']}/items?per_page=100", token)
                    for child in children:
                        normalized.append({"id": f"canvas:{course['id']}:module:{child['id']}", "source": "canvas",
                            "course_id": str(course["id"]), "kind": kind, "title": child.get("title", "资料"),
                            "description": "", "url": safe_url(child.get("html_url") or child.get("external_url") or ""),
                            "attachments": [], "updated_at": None, "group": raw.get("name", "学习单元")})
                    continue
                ident = raw.get("id") or raw.get("page_id") or raw.get("url")
                # Use authenticated file pages rather than persisting signed download URLs.
                url = base + f"/courses/{course['id']}/files/{raw['id']}" if kind == "file" else raw.get("html_url", "")
                normalized.append({"id": f"canvas:{course['id']}:{kind}:{ident}", "source": "canvas",
                    "course_id": str(course["id"]), "kind": kind,
                    "title": raw.get("title") or raw.get("display_name") or raw.get("filename", "资料"),
                    "description": plain_html(raw.get("message", "")), "url": safe_url(url),
                    "attachments": html_links(raw.get("message", ""), url),
                    "updated_at": raw.get("updated_at") or raw.get("posted_at"), "group": ""})
            records.extend(normalized)
        except (UserError, ValueError, KeyError, TypeError) as error:
            failed.add(f"{course['id']}:{kind}")
            detail = str(error) if isinstance(error, UserError) else "资料格式异常。"
            warnings.append(f"{course.get('name', '课程')}（{kind}）：{detail}")
    return records, failed, warnings


def fetch_canvas(base: str, token: str) -> Batch:
    courses = canvas_pages(base + "/api/v1/courses?enrollment_type=student&enrollment_state=active&per_page=100", token)
    batch = Batch(course_ids={str(c["id"]) for c in courses})
    for course in courses:
        batch.courses.append(course_record("canvas", course, base + f"/courses/{course['id']}"))
        try:
            raw = canvas_pages(base + f"/api/v1/courses/{course['id']}/assignments?per_page=100&include[]=submission", token)
            normalized = [canvas_assignment(base, course, item) for item in raw if item.get("published", True)]
            batch.items.extend(normalized)
        except (UserError, ValueError, KeyError, TypeError) as error:
            batch.failed_courses.add(str(course["id"]))
            detail = str(error) if isinstance(error, UserError) else "作业日期或数据格式异常。"
            batch.warnings.append(f"{course.get('name', '课程')}：{detail}")
        resources, failed, warnings = canvas_resources(base, token, course)
        batch.resources.extend(resources)
        batch.failed_resources.update(failed)
        batch.warnings.extend(warnings)
    return batch


def fetch_classroom(token: str) -> Batch:
    root = "https://classroom.googleapis.com/v1/courses"
    courses = google_pages(root, token, "courses", {"studentId": "me", "courseStates": "ACTIVE"})
    batch = Batch(course_ids={str(c["id"]) for c in courses})
    for course in courses:
        batch.courses.append(course_record("classroom", course, course.get("alternateLink", "")))
        try:
            works = google_pages(root + f"/{course['id']}/courseWork", token, "courseWork")
            submissions = {}
            try:
                raw = google_pages(root + f"/{course['id']}/courseWork/-/studentSubmissions", token,
                                   "studentSubmissions", {"userId": "me"})
                submissions = {str(item["courseWorkId"]): item for item in raw}
            except UserError as error:
                batch.warnings.append(f"{course.get('name', '课程')}：提交状态读取失败，{error}")
            normalized = [classroom_assignment(course, item, submissions.get(str(item["id"])))
                          for item in works if item.get("state", "PUBLISHED") == "PUBLISHED"]
            batch.items.extend(normalized)
        except (UserError, ValueError, KeyError, TypeError) as error:
            batch.failed_courses.add(str(course["id"]))
            detail = str(error) if isinstance(error, UserError) else "作业日期或数据格式异常。"
            batch.warnings.append(f"{course.get('name', '课程')}：{detail}")
        for kind, endpoint, key in [("material", "courseWorkMaterials", "courseWorkMaterial"),
                                    ("announcement", "announcements", "announcements")]:
            try:
                resources = []
                for item in google_pages(root + f"/{course['id']}/{endpoint}", token, key):
                    resources.append({"id": f"classroom:{course['id']}:{kind}:{item['id']}",
                                      "source": "classroom", "course_id": str(course["id"]), "kind": kind,
                                      "title": item.get("title") or item.get("text", "公告")[:80],
                                      "description": item.get("description") or item.get("text", ""),
                                      "url": safe_url(item.get("alternateLink", "")),
                                      "attachments": google_attachments(item),
                                      "updated_at": item.get("updateTime"), "group": ""})
                batch.resources.extend(resources)
            except (UserError, ValueError, KeyError, TypeError) as error:
                batch.failed_resources.add(f"{course['id']}:{kind}")
                detail = str(error) if isinstance(error, UserError) else "资料数据格式异常。"
                batch.warnings.append(f"{course.get('name', '课程')}：资料读取失败，{detail}")
    return batch


def merge_batch(previous: list, source: str, batch: Batch) -> list:
    retained = [item for item in previous if item["source"] != source or
                item["course_id"] in batch.failed_courses]
    return sorted({item["id"]: item for item in retained + batch.items}.values(),
                  key=lambda item: (item["due_at"] is None, item["due_at"] or "", item["id"]))


def merge_resources(previous: list, source: str, batch: Batch) -> list:
    retained = [item for item in previous if item["source"] != source or
                f"{item['course_id']}:{item['kind']}" in batch.failed_resources]
    return list({item["id"]: item for item in retained + batch.resources}.values())


def ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace(
        "\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold_line(line: str) -> str:
    lines, current = [], ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            lines.append(current)
            current = " "
        current += char
    lines.append(current)
    return "\r\n".join(lines)


def export_ics(items: list) -> bytes:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Student Calendar//ZH", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:作业日历", "X-WR-TIMEZONE:Asia/Tokyo"]
    for item in items:
        due = parse_time(item.get("due_at"))
        if due is None:
            continue
        description = f"{item['source']} · {item['course']}\n" + item.get("description", "")
        lines.extend(["BEGIN:VEVENT", "UID:" + ics_escape(item["id"]) + "@student-calendar.local",
                      "DTSTAMP:" + stamp, "DTSTART:" + due.strftime("%Y%m%dT%H%M%SZ"),
                      "DTEND:" + (due + timedelta(minutes=1)).strftime("%Y%m%dT%H%M%SZ"),
                      "SUMMARY:" + ics_escape(f"[{item['course']}] {item['title']}"),
                      "DESCRIPTION:" + ics_escape(description), "TRANSP:TRANSPARENT"])
        if safe_url(item.get("url", "")):
            lines.append("URL:" + ics_escape(item["url"]))
        lines.extend(["BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY", "DESCRIPTION:作业明天截止",
                      "END:VALARM", "END:VEVENT"])
    lines.append("END:VCALENDAR")
    return ("\r\n".join(fold_line(line) for line in lines) + "\r\n").encode("utf-8")


def demo_items() -> list:
    today = datetime.now(JST).date()
    rows = [("canvas", "电子回路 II", "第 6 回演习", 0, "pending"),
            ("classroom", "微观经济学", "需求与弹性练习", 1, "pending"),
            ("canvas", "电气实验", "直流电源实验报告", 3, "pending"),
            ("classroom", "英语", "Reading response", 5, "submitted"),
            ("canvas", "数学", "积分习题", -1, "pending"),
            ("classroom", "物理", "预习问题", None, "pending")]
    items = []
    for index, (source, course, title, offset, status) in enumerate(rows):
        due = datetime.combine(today + timedelta(days=offset), datetime.min.time(), JST).replace(
            hour=23, minute=59).astimezone(UTC).isoformat() if offset is not None else None
        items.append({"id": f"demo:{index}", "source": source, "course_id": str(index), "course": course,
                      "title": title, "description": "这是演示数据，用于预览日历效果，并非你的真实作业。",
                      "due_at": due, "status": status, "url": "", "updated_at": None})
    return items
