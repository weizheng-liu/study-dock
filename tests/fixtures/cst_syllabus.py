"""Trimmed responses shaped exactly like the public 理工学部 endpoints (captured 2026-11-27)."""

OPTIONS = {"result": "success",
    "nendoDataList": [{"nendo": "2025"}, {"nendo": "2026"}],
    "gakubuDataList": [{"nendo": "2026", "gakubuKbn": "1", "gakubuMei": "理工学部", "syoumeiGakubuMei": "理工学部", "koukaiFlag": "Y"}],
    "gakkaDataList": [
        {"nendo": "2026", "gakubuKbn": "1", "gakkaCD": "02", "gakkaMei": "交通システム工学科", "koukaiFlag": "Y"},
        {"nendo": "2026", "gakubuKbn": "1", "gakkaCD": "15", "gakkaMei": "応用情報工学科", "koukaiFlag": "Y"},
        {"nendo": "2026", "gakubuKbn": "1", "gakkaCD": "99", "gakkaMei": "一般教育", "koukaiFlag": "Y"}],
    "courseDataList": [
        {"nendo": "2026", "gakubuKbn": "1", "gakkaCD": "02", "courseCD": "0", "courseMei": "エンジニアリングコース", "koukaiFlag": "Y", "hyoujiFlag": "Y"},
        {"nendo": "2026", "gakubuKbn": "1", "gakkaCD": "02", "courseCD": "2", "courseMei": "マネジメントコース", "koukaiFlag": "Y", "hyoujiFlag": "Y"},
        {"nendo": "2026", "gakubuKbn": "1", "gakkaCD": "15", "courseCD": "0", "courseMei": "", "koukaiFlag": "Y", "hyoujiFlag": "Y"},
        {"nendo": "2026", "gakubuKbn": "1", "gakkaCD": "99", "courseCD": "0", "courseMei": "", "koukaiFlag": "Y", "hyoujiFlag": "Y"}]}


def klass(code, title, teacher, names, youbi="水曜", jigen="1-2", term="後期", dept="応用情報工学科", bikou=""):
    return {"youbi": 4, "youbiMei": youbi, "jigen": 1, "jigenMei": jigen, "nendo": "2026", "jikanwariCD": code,
            "kamokuMei": title, "bikou": bikou, "gakubuKbn": "1", "gakkaCD": "15", "gakkaMei": dept,
            "courseCD": "0", "risyukiKbn": "31", "risyukiMei": term, "gakunen": "1", "kousyaCD": "F",
            "kyositsuMei": "1201 1204", "KyouinData": [{"kyouinCD": str(i), "kyouinMei": n, "renmeiFlag": "-"} for i, n in enumerate(names)],
            "kyouinMei": teacher, "setiKbnMei": "学科配当科目", "tokkiJikou": "", "kamokuKbnMei": "専門教育科目"}


CLASSES_15 = {"result": "success", "kamokuDataList": [
    klass("K31B", "Ｃプログラミング及び演習", "香取・滕・関", ["香取　照臣", "滕　琳", "関　弘翔"]),
    klass("K31B", "Ｃプログラミング及び演習", "香取・滕・関", ["香取　照臣", "滕　琳", "関　弘翔"], youbi="金曜", jigen="3"),
    klass("K52E", "オブジェクト指向プログラミング", "滕　琳", ["滕　琳"], youbi="金曜", jigen="2", term="前期"),
    klass("K32B", "論理回路", "香取　照臣", ["香取　照臣"]),
]}
CLASSES_99 = {"result": "success", "kamokuDataList": [
    klass("T11A", "English Communication Ⅰ", "IAN EDWARD ELLSWORTH", ["IAN EDWARD ELLSWORTH"], dept="一般教育")]}


def schedule(seq, index, content, date):
    return {"classSchedule": {"setiNendo": "2026", "pageID": 5729, "seqNo": seq, "content": content,
            "studies": "事前学修：教科書で予習する。\r\n事後学修：演習問題で復習する。", "benchmark": "",
            "startDate": date, "endDate": "", "category": 1, "isOnline": 1, "displayIndex": index, "displaySubIndex": 1},
            "tantouKyouin": {}}


COURSE_K31B = {"dataType": "CourseView", "result": "success", "errorMessage": None, "courseViewData": {
    "gakkaCD": "15", "gakubuKbn": "1", "syllabusData": {
        "kamokuGaiyou": None,
        "texts": [{"name": "明快入門C", "author": "林　晴比古", "publisher": "ソフトバンククリエイティブ（株）", "publicationYear": "2013"}],
        "supplies": [{"name": "UNIXとC", "author": "阿曽弘具", "publisher": "近代科学社", "publicationYear": "1994"}],
        "officeHours": [{"youbi": "6", "kosya": "F", "hourFrom": "12:35", "hourTo": "13:15", "remark": "香取　照臣."}],
        "page": {"courseObjectives": "C言語を使ってプログラミング技能を修得する。", "lectureForm": "講義及び演習",
                 "prerequisite": "必修。\r\n情報基礎演習IIとの同時受講が望ましい。", "outOfClassWork": "",
                 "textsRemarks": "", "suppliesRemarks": "", "subtitle": "",
                 "evaluation": "○演習・課題レポート（４０％）\n○中間テスト（３０％）\n○理解度確認テスト（３０％）",
                 "respondingToQuestions": "随時研究室にて．", "contactInformation": "船橋校舎２号館", "messageToStutdents": "",
                 "dpCpNote": "本授業科目はDP1・3・5に該当しています。"},
        "classScheduleData": [dict(schedule(9, 1, "開発環境構築", "20260916"), classSchedule=dict(schedule(9, 1, "開発環境構築", "20260916")["classSchedule"], category=2)),
                              schedule(0, 1, "ネチケットとC言語", "20260930"), schedule(1, 1, "ネチケットとC言語", "20260930"),
                              schedule(2, 2, "条件判断", "20261007")],
        "kamou": {"kamokuMei": "Ｃプログラミング及び演習", "taniSu": 3},
        "authors": [{"kyouinMei": "香取　照臣"}, {"kyouinMei": "滕　琳"}],
    }}}
