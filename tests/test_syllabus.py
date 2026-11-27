from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import Portal
from core import UserError
import syllabus
from study_assistant import ask
from fixtures.cst_syllabus import CLASSES_15, CLASSES_99, COURSE_K31B, OPTIONS

PREFS = {"nendo": "2026", "faculty": "1", "departments": ["15", "99"]}


class FakeSite:
    def __init__(self):
        self.calls = []
        self.down = False

    def __call__(self, path, payload=None):
        self.calls.append((path, payload))
        if self.down:
            raise UserError("暂时连不上学校シラバス系统，请检查网络后重试。")
        if path == "/timetable/App/GakubuData":
            return OPTIONS
        if path == "/timetable/App/KamokuData":
            if not payload.get("gakkaCD") or payload.get("courseCD") == "":
                raise UserError("理工学部时间割系统拒绝了这次查询，请确认年度和学科。")
            return {"15": CLASSES_15, "99": CLASSES_99}.get(payload["gakkaCD"], {"result": "success", "kamokuDataList": []})
        if path.startswith("/syllabus/View/Course?") and "jikanwariCD=K31B" in path:
            return COURSE_K31B
        return {"dataType": "CourseView", "courseViewData": {"syllabusData": None}}


class SyllabusServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = FakeSite()
        self.now = [1_000_000.0]
        self.service = syllabus.SyllabusService(Path(self.temp.name), self.site, lambda: self.now[0])

    def test_width_insensitive_search_merges_slots(self):
        result = self.service.search(PREFS, "c プログラミング")
        codes = [r["code"] for r in result["results"]]
        self.assertEqual(codes, ["K31B"])
        self.assertEqual(result["results"][0]["slots"], ["水曜1-2限", "金曜3限"])
        self.assertIn("/syllabus/Publication/2026/course/1/K31B", result["results"][0]["url"])

    def test_teacher_code_and_multi_term_search(self):
        self.assertEqual({r["code"] for r in self.service.search(PREFS, "香取")["results"]}, {"K31B", "K32B"})
        self.assertEqual([r["code"] for r in self.service.search(PREFS, "k52e")["results"]], ["K52E"])
        self.assertEqual([r["code"] for r in self.service.search(PREFS, "滕 オブジェクト")["results"]], ["K52E"])
        self.assertEqual([r["code"] for r in self.service.search(PREFS, "english")["results"]], ["T11A"])

    def test_catalog_is_cached_and_survives_outage(self):
        self.service.search(PREFS, "論理")
        fetched = len(self.site.calls)
        self.service.search(PREFS, "論理")
        self.assertEqual(len(self.site.calls), fetched)
        fresh = syllabus.SyllabusService(Path(self.temp.name), self.site, lambda: self.now[0])
        fresh.search(PREFS, "論理")
        self.assertEqual(len(self.site.calls), fetched, "disk cache should be reused")
        self.now[0] += syllabus.CATALOG_TTL + 1
        self.site.down = True
        self.assertEqual(fresh.search(PREFS, "論理")["results"][0]["code"], "K32B")

    def test_course_code_required_for_departments_with_courses(self):
        self.service.catalog({"nendo": "2026", "faculty": "1", "departments": ["02"]})
        sent = [p["courseCD"] for path, p in self.site.calls if p]
        self.assertEqual(sent, ["0", "2"])

    def test_prefs_validation(self):
        for bad in ({"nendo": "2019", "departments": ["15"]}, {"nendo": "2026", "departments": []},
                    {"nendo": "2026", "departments": ["77"]}, None):
            with self.assertRaises(UserError):
                self.service.check_prefs(bad)
        with self.assertRaises(UserError):
            self.service.search(PREFS, " ")

    def test_detail_parsing(self):
        detail = self.service.detail("2026", "1", "k31b")
        self.assertEqual(detail["title"], "Ｃプログラミング及び演習")
        self.assertEqual(detail["credits"], 3)
        self.assertEqual(detail["teachers"], ["香取 照臣", "滕 琳"])
        self.assertEqual([(s["number"], s["online"]) for s in detail["schedule"]], [(1, False), (2, False), (1, True)],
                         "repeated periods collapse; on-demand sessions go last")
        self.assertEqual(detail["schedule"][0]["date"], "2026-09-30")
        self.assertIn("中間テスト", next(s["text"] for s in detail["sections"] if s["title"] == "成績評価の方法"))
        self.assertTrue(detail["textbooks"][0].startswith("明快入門C"))
        self.assertEqual(detail["office_hours"], ["金曜 12:35–13:15 香取　照臣."])
        self.assertIn("第2回 2026-10-07 条件判断", syllabus.detail_text(detail))
        with self.assertRaises(UserError):
            self.service.detail("2026", "1", "Z99Z")
        with self.assertRaises(UserError):
            self.service.detail("2026", "1", "../x")

    def test_suggest_prefers_code_then_longest_title(self):
        catalog = self.service.catalog(PREFS)
        self.assertEqual(syllabus.suggest("2026後期 Cプログラミング及び演習(K31B)", catalog)[0]["code"], "K31B")
        self.assertEqual(syllabus.suggest("【K32B】月曜クラス", catalog)[0]["code"], "K32B")
        self.assertEqual(syllabus.suggest("オブジェクト指向プログラミング 2026", catalog)[0]["code"], "K52E")
        self.assertEqual(syllabus.suggest("電子回路", catalog), [])


class PortalSyllabusTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = Portal(self.root, {})
        self.app.syllabus = syllabus.SyllabusService(self.root / "syllabus", FakeSite())
        self.one = self.app.db.register("student-one", "test-password-1")
        self.two = self.app.db.register("student-two", "test-password-2")
        self.course = {"id": "canvas:11", "course_id": "11", "name": "Ｃプログラミング及び演習", "source": "canvas", "url": ""}
        self.cache = {"items": [], "courses": [self.course], "resources": [], "providers": {}, "last_attempt_at": None}
        self.app.db.write(self.one, "cache", self.cache)

    def test_prefs_link_and_assistant_context_are_per_user(self):
        with self.assertRaises(UserError):
            self.app.syllabus_suggest(self.one, {"course": "canvas:11"})
        self.app.syllabus_prefs(self.one, PREFS)
        suggestion = self.app.syllabus_suggest(self.one, {"course": "canvas:11"})["suggestions"][0]
        self.assertEqual(suggestion["code"], "K31B")
        self.app.syllabus_link(self.one, {"course": "canvas:11", "code": "K31B", "nendo": "2026", "faculty": "1"})
        self.assertEqual(self.app.state(self.one)["syllabus_links"]["canvas:11"]["code"], "K31B")
        self.assertEqual(self.app.state(self.two)["syllabus_links"], {})
        with self.assertRaises(UserError):
            self.app.syllabus_link(self.two, {"course": "canvas:11", "code": "K31B", "nendo": "2026"})
        context = self.app.syllabus_context(self.one)
        self.assertEqual(context[0]["course"], "Ｃプログラミング及び演習")
        self.assertEqual(self.app.syllabus_context(self.two), [])
        self.app.syllabus_link(self.one, {"course": "canvas:11"})
        doc = self.app.db.read(self.one, "syllabus", {})
        self.assertEqual(doc["links"], {})
        self.assertEqual(doc["details"], {}, "unlinked snapshots are dropped")

    @patch("study_assistant.generate", return_value="评分见 [1]")
    def test_assistant_cites_linked_syllabus(self, generate):
        self.app.syllabus_prefs(self.one, PREFS)
        self.app.syllabus_link(self.one, {"course": "canvas:11", "code": "K31B", "nendo": "2026", "faculty": "1"})
        cache = dict(self.cache, syllabi=self.app.syllabus_context(self.one))
        result = ask(self.root, cache, {"question": "Ｃプログラミング及び演習怎么评分？"})
        facts = generate.call_args.args[-1]["可用记录"]
        self.assertIn("中間テスト", facts["1"]["内容"])
        self.assertEqual(result["sources"][0]["url"], syllabus.public_url("2026", "1", "K31B"))


if __name__ == "__main__":
    unittest.main()
