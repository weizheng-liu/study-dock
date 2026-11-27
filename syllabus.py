"""Public syllabus lookup for Nihon University College of Science and Technology (理工学部).

The faculty's web timetable and syllabus pages are single-page apps backed by public JSON
endpoints that need no login or cookie:

* ``GET  /timetable/App/GakubuData``  – years, faculties, departments and courses
* ``POST /timetable/App/KamokuData``  – every class of one department in one year
* ``GET  /syllabus/View/Course``      – one class's syllabus

The server only does exact substring matching (a half-width "C" does not find a full-width
"Ｃ"), so Study Dock downloads a department's class list once, caches it, and matches
locally after NFKC normalization.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import threading
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from core import JST, NoRedirect, UserError

HOST = "https://www.kyoumu.cst.nihon-u.ac.jp"
CATALOG_TTL = 24 * 3600
DETAIL_TTL = 7 * 24 * 3600
MAX_BYTES = 8 * 1024 * 1024
CODE = re.compile(r"[A-Z0-9]{3,6}")
YEAR = re.compile(r"20\d{2}")
DIGITS = re.compile(r"\d{1,2}")
WEEKDAYS = {"1": "日", "2": "月", "3": "火", "4": "水", "5": "木", "6": "金", "7": "土"}


def normalize(text) -> str:
    """Fold width, case and spacing so that 'c プログラミング' finds 'Ｃプログラミング'."""
    folded = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.sub(r"[\s・･,，、.。/／()（）\[\]【】「」_\-‐－]+", "", folded)


def plain(text) -> str:
    return re.sub(r"\r\n?", "\n", str(text or "")).strip()


def academic_year(now: datetime | None = None) -> str:
    now = (now or datetime.now(JST)).astimezone(JST)
    return str(now.year if now.month >= 4 else now.year - 1)


def public_url(nendo: str, gakubu: str, code: str) -> str:
    return f"{HOST}/syllabus/Publication/{nendo}/course/{gakubu}/{code}"


def fetch(path: str, payload: dict | None = None):
    """GET (or POST JSON to) a public endpoint. Never sends cookies or credentials."""
    headers = {"Accept": "application/json", "User-Agent": "StudyDock/1.0 (syllabus lookup)"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode()
    request = Request(HOST + path, data=data, headers=headers)
    try:
        with build_opener(NoRedirect).open(request, timeout=25) as response:
            body = response.read(MAX_BYTES + 1)
    except HTTPError as error:
        error.close()
        if error.code == 500 and payload is not None:
            raise UserError("理工学部时间割系统拒绝了这次查询，请确认年度和学科。") from None
        raise UserError(f"学校シラバス系统返回 HTTP {error.code}，请稍后重试。") from None
    except (URLError, TimeoutError, OSError):
        raise UserError("暂时连不上学校シラバス系统，请检查网络后重试。") from None
    if len(body) > MAX_BYTES:
        raise UserError("学校返回的数据过大，已停止读取。")
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise UserError("学校シラバス系统返回的不是预期格式，可能已经改版。") from None


class SyllabusService:
    """Caches public data on disk; it is the same for every user, so the cache is shared."""

    def __init__(self, directory: Path, fetcher=fetch, clock=time.time):
        self.directory = directory
        self.fetch = fetcher
        self.clock = clock
        self.lock = threading.Lock()
        self.memory = {}

    # ---------- cache ----------
    def _cached(self, name: str, ttl: float, load):
        path = self.directory / name
        with self.lock:
            entry = self.memory.get(name)
            if entry is None and path.exists():
                try:
                    entry = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    entry = None
            if entry and self.clock() - entry.get("fetched_at", 0) < ttl:
                self.memory[name] = entry
                return entry["data"]
        try:
            data = load()
        except UserError:
            if entry:  # Stale data beats no data when the school site is down.
                return entry["data"]
            raise
        entry = {"fetched_at": self.clock(), "data": data}
        with self.lock:
            self.memory[name] = entry
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        return data

    # ---------- options ----------
    def options(self) -> dict:
        raw = self._cached("options.json", CATALOG_TTL, lambda: self.fetch("/timetable/App/GakubuData"))
        if not isinstance(raw, dict) or raw.get("result") != "success":
            raise UserError("学校没有返回年度和学科列表，请稍后重试。")
        visible = lambda row: isinstance(row, dict) and row.get("koukaiFlag", "Y") == "Y"
        years = sorted({str(r.get("nendo")) for r in raw.get("nendoDataList") or [] if YEAR.fullmatch(str(r.get("nendo")))},
                       reverse=True)
        faculties = [{"nendo": r["nendo"], "code": r["gakubuKbn"], "name": r.get("syoumeiGakubuMei") or r.get("gakubuMei")}
                     for r in raw.get("gakubuDataList") or [] if visible(r)]
        departments = [{"nendo": r["nendo"], "faculty": r["gakubuKbn"], "code": r["gakkaCD"], "name": r.get("gakkaMei", "")}
                       for r in raw.get("gakkaDataList") or [] if visible(r)]
        courses = [{"nendo": r["nendo"], "faculty": r["gakubuKbn"], "department": r["gakkaCD"],
                    "code": r.get("courseCD", "0"), "name": r.get("courseMei", "")}
                   for r in raw.get("courseDataList") or [] if visible(r) and r.get("hyoujiFlag", "Y") == "Y"]
        return {"years": years, "faculties": faculties, "departments": departments, "courses": courses,
                "default_year": academic_year() if academic_year() in years else (years[0] if years else "")}

    def check_prefs(self, prefs) -> dict:
        if not isinstance(prefs, dict):
            raise UserError("请选择年度和学科。")
        nendo, faculty = str(prefs.get("nendo", "")), str(prefs.get("faculty", "1"))
        departments = prefs.get("departments")
        if not isinstance(departments, list) or not 1 <= len(departments) <= 6:
            raise UserError("请选择 1 至 6 个学科（一般教育科目选「一般教育」）。")
        options = self.options()
        if nendo not in options["years"]:
            raise UserError("学校还没有公开这个年度的时间割。")
        known = {(d["code"]) for d in options["departments"] if d["nendo"] == nendo and d["faculty"] == faculty}
        departments = list(dict.fromkeys(str(d) for d in departments))
        if not known or not set(departments) <= known:
            raise UserError("学科不在学校公开的列表里，请重新选择。")
        return {"nendo": nendo, "faculty": faculty, "departments": departments}

    # ---------- catalog ----------
    def course_codes(self, prefs: dict, department: str) -> list[str]:
        codes = [c["code"] for c in self.options()["courses"]
                 if c["nendo"] == prefs["nendo"] and c["faculty"] == prefs["faculty"] and c["department"] == department]
        return list(dict.fromkeys(codes)) or ["0"]

    def department(self, prefs: dict, department: str) -> list[dict]:
        rows = []
        for course in self.course_codes(prefs, department):
            name = f"classes-{prefs['nendo']}-{prefs['faculty']}-{department}-{course}.json"
            body = {"nendo": prefs["nendo"], "gakubuKbn": prefs["faculty"], "gakkaCD": department, "courseCD": course,
                    "kousya": [], "risyukiKbn": [], "gakunen": [], "kamokuMei": "", "jikanwariCD": "",
                    "kyousituMei": "", "kyouinMei": "", "jigen": [], "renzokujigen": True}
            raw = self._cached(name, CATALOG_TTL, lambda body=body: self.fetch("/timetable/App/KamokuData", body))
            if not isinstance(raw, dict) or raw.get("result") != "success":
                raise UserError("学校没有返回科目列表，请稍后重试。")
            rows.extend(raw.get("kamokuDataList") or [])
        return rows

    def catalog(self, prefs: dict) -> list[dict]:
        merged = {}
        for department in prefs["departments"]:
            for raw in self.department(prefs, department):
                code = str(raw.get("jikanwariCD", ""))
                if not CODE.fullmatch(code) or not raw.get("kamokuMei"):
                    continue
                entry = merged.get(code)
                slot = f"{raw.get('youbiMei', '')}{raw['jigenMei']}限" if raw.get("jigenMei") else ""
                if entry:  # One class can appear in several weekday slots.
                    if slot and slot not in entry["slots"]:
                        entry["slots"].append(slot)
                    continue
                teachers = [t.get("kyouinMei", "").replace("　", " ") for t in raw.get("KyouinData") or []
                            if isinstance(t, dict) and t.get("kyouinMei")]
                merged[code] = {
                    "code": code, "nendo": prefs["nendo"], "faculty": prefs["faculty"],
                    "title": plain(raw["kamokuMei"]), "note": plain(raw.get("bikou")),
                    "teacher": plain(raw.get("kyouinMei")).replace("　", " "), "teachers": teachers,
                    "department": raw.get("gakkaMei", ""), "term": raw.get("risyukiMei", ""),
                    "grade": raw.get("gakunen", ""), "slots": [slot] if slot else [],
                    "room": plain(raw.get("kyositsuMei")), "category": raw.get("kamokuKbnMei", ""),
                    "url": public_url(prefs["nendo"], prefs["faculty"], code)}
        return list(merged.values())

    def search(self, prefs: dict, query, limit: int = 60) -> dict:
        if not isinstance(query, str) or not 0 < len(query.strip()) <= 100:
            raise UserError("请输入 1 至 100 字的科目名、老师名或时间割代码。")
        prefs = self.check_prefs(prefs)
        terms = [normalize(t) for t in query.split() if normalize(t)]
        if not terms:
            raise UserError("请输入科目名、老师名或时间割代码。")
        scored = []
        for row in self.catalog(prefs):
            title = normalize(row["title"])
            fields = [title, normalize(row["teacher"]), *map(normalize, row["teachers"]), normalize(row["code"])]
            if not all(any(term in field for field in fields) for term in terms):
                continue
            exact = sum(term == title or term == normalize(row["code"]) for term in terms)
            scored.append(((-exact, len(title), row["code"]), row))
        scored.sort(key=lambda pair: pair[0])
        return {"results": [row for _, row in scored[:limit]], "total": len(scored), "prefs": prefs}

    # ---------- detail ----------
    def detail(self, nendo, faculty, code) -> dict:
        nendo, faculty, code = str(nendo or ""), str(faculty or "1"), str(code or "").strip().upper()
        if not YEAR.fullmatch(nendo) or not DIGITS.fullmatch(faculty) or not CODE.fullmatch(code):
            raise UserError("时间割代码格式不正确。")
        query = urlencode({"setiNendo": nendo, "gakubu": faculty, "jikanwariCD": code, "pageID": "", "flag": ""})
        raw = self._cached(f"syllabus-{nendo}-{faculty}-{code}.json", DETAIL_TTL,
                           lambda: self.fetch("/syllabus/View/Course?" + query))
        return parse_detail(raw, nendo, faculty, code)


def _books(rows) -> list[str]:
    books = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        extra = "，".join(x for x in (row.get("author"), row.get("publisher"), row.get("publicationYear")) if x)
        books.append(plain(row["name"]) + (f"（{extra}）" if extra else ""))
    return books


def parse_detail(raw, nendo: str, faculty: str, code: str) -> dict:
    view = raw.get("courseViewData") if isinstance(raw, dict) else None
    data = (view or {}).get("syllabusData") if isinstance(view, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("page"), dict):
        raise UserError("学校还没有公开这门课的シラバス，或时间割代码不存在。")
    page, subject = data["page"], data.get("kamou") or {}
    teachers = [plain(t.get("kyouinMei")).replace("　", " ") for t in data.get("authors") or data.get("kyouins") or []
                if isinstance(t, dict) and t.get("kyouinMei")]
    schedule, seen = [], set()
    for entry in data.get("classScheduleData") or []:
        row = entry.get("classSchedule") if isinstance(entry, dict) else None
        if not isinstance(row, dict) or not row.get("content"):
            continue
        number = row.get("displayIndex")
        content = plain(row["content"])
        key = (number, content)
        if key in seen:  # Consecutive periods repeat the same plan twice.
            continue
        seen.add(key)
        start = str(row.get("startDate") or "")
        date = f"{start[:4]}-{start[4:6]}-{start[6:8]}" if re.fullmatch(r"\d{8}", start) else ""
        schedule.append({"number": number, "date": date, "content": content, "study": plain(row.get("studies")),
                         "online": row.get("category") == 2})
    # On-demand sessions are numbered separately from classroom sessions; list them last.
    schedule.sort(key=lambda r: (r["online"], r["number"] if isinstance(r["number"], int) else 0))
    hours = []
    for row in data.get("officeHours") or []:
        if isinstance(row, dict) and row.get("hourFrom"):
            day = WEEKDAYS.get(str(row.get("youbi")), "")
            hours.append(f"{day}曜 {row['hourFrom']}–{row.get('hourTo', '')} {plain(row.get('remark'))}".strip())
    sections = [("授業の到達目標とテーマ", page.get("courseObjectives")), ("授業の形態・概要", page.get("lectureForm")),
                ("履修条件", page.get("prerequisite")), ("授業時間外の学修", page.get("outOfClassWork")),
                ("成績評価の方法", page.get("evaluation")), ("質問への対応", page.get("respondingToQuestions")),
                ("連絡先", page.get("contactInformation")), ("学生へのメッセージ", page.get("messageToStutdents")),
                ("DP・CP", page.get("dpCpNote"))]
    return {"code": code, "nendo": nendo, "faculty": faculty, "url": public_url(nendo, faculty, code),
            "title": plain(subject.get("kamokuMei")) or code, "subtitle": plain(page.get("subtitle")),
            "credits": subject.get("taniSu"), "teachers": teachers,
            "sections": [{"title": title, "text": plain(text)} for title, text in sections if plain(text)],
            "textbooks": _books(data.get("texts")), "references": _books(data.get("supplies")),
            "textbook_note": plain(page.get("textsRemarks")), "reference_note": plain(page.get("suppliesRemarks")),
            "office_hours": hours, "schedule": schedule}


def detail_text(detail: dict, limit: int = 3500) -> str:
    """A compact plain-text version that the study assistant can cite."""
    lines = [f"{detail['title']}（{detail['code']}，{detail.get('credits') or '?'} 単位，担当：{'、'.join(detail['teachers'])}）"]
    for section in detail["sections"]:
        lines.append(f"【{section['title']}】{section['text']}")
    if detail["textbooks"]:
        lines.append("【教科書】" + "；".join(detail["textbooks"]))
    if detail["references"]:
        lines.append("【参考書】" + "；".join(detail["references"]))
    if detail["office_hours"]:
        lines.append("【オフィスアワー】" + "；".join(detail["office_hours"]))
    for row in detail["schedule"]:
        label = f"オンデマンド{row['number']}" if row["online"] else f"第{row['number']}回"
        lines.append(f"{label} {row['date']} {row['content']}".replace("\n", " "))
    return "\n".join(lines)[:limit]


def suggest(course_name: str, catalog: list[dict], limit: int = 5) -> list[dict]:
    """Rank catalog classes for a Canvas / Classroom course name.

    A timetable code in the course name (e.g. 'K31B') is decisive. Otherwise the longest
    syllabus title contained in the normalized course name wins."""
    name = normalize(course_name)
    upper = unicodedata.normalize("NFKC", course_name or "").upper()
    if not name:
        return []
    scored = []
    for row in catalog:
        title = normalize(row["title"])
        if re.search(rf"(?<![A-Z0-9]){re.escape(row['code'])}(?![A-Z0-9])", upper):
            score = 1000
        elif title and title in name:
            score = 100 + len(title)
        elif len(name) >= 3 and name in title:
            score = 50 + len(name)
        else:
            continue
        scored.append((-score, row["code"], row))
    scored.sort(key=lambda r: (r[0], r[1]))
    return [dict(row, score=-score) for score, _, row in scored[:limit]]
