/* School syllabus (シラバス) lookup: Nihon University College of Science and Technology.
   Public data fetched by the local server; nothing here needs a school login. */
'use strict';
let syllabusOptions = null, syllabusLoading = false, syllabusError = '';
let syllabusQuery = '', syllabusResults = null, syllabusSearching = false, syllabusEditing = false;
const syllabusDetails = {}, syllabusSuggestions = {};

async function loadSyllabusOptions(force = false) {
  if (syllabusLoading || (syllabusOptions && !force)) return;
  syllabusLoading = true; syllabusError = '';
  try { syllabusOptions = await api('/api/syllabus/options', {}); }
  catch (error) { syllabusError = error.message; }
  finally { syllabusLoading = false; render(); }
}

function syllabusDepartmentName(prefs, code) {
  const row = syllabusOptions?.departments.find(d => d.nendo === prefs.nendo && d.faculty === prefs.faculty && d.code === code);
  return row ? row.name : code;
}

function renderSyllabus(main) {
  const actions = E('div', 'row');
  if (syllabusOptions?.prefs && !syllabusEditing) actions.append(button('更改年度 / 学科', () => { syllabusEditing = true; render(); }, 'button secondary'));
  main.append(heading('课程大纲', '直接查日大理工学部官网公开的シラバス：授课计划、评分方法、教材，一页看完。', actions));
  if (demo) return main.append(empty('演示模式不查询学校网站，请登录后使用。'));
  if (!syllabusOptions) {
    loadSyllabusOptions();
    return main.append(empty(syllabusError || '正在读取学校公开的年度和学科列表…'));
  }
  if (!syllabusOptions.prefs || syllabusEditing) return main.append(syllabusSetup());
  const prefs = syllabusOptions.prefs;
  const panel = E('section', 'panel');
  const form = E('form', 'toolbar');
  const input = E('input', 'input search');
  input.placeholder = '科目名、老师名或时间割代码，例如：プログラミング / 香取 / K31B';
  input.setAttribute('aria-label', '搜索课程大纲');
  input.value = syllabusQuery; input.maxLength = 100;
  input.addEventListener('input', () => { syllabusQuery = input.value; });
  const submit = E('button', 'button', syllabusSearching ? '正在查询…' : '查询');
  submit.type = 'submit'; submit.disabled = syllabusSearching;
  form.addEventListener('submit', event => { event.preventDefault(); searchSyllabus(input.value); });
  form.append(input, submit);
  panel.append(form, E('p', 'caption', `${prefs.nendo} 年度 · ${prefs.departments.map(c => syllabusDepartmentName(prefs, c)).join('、')}。全角半角、大小写都不用管。`));
  if (syllabusResults) {
    if (!syllabusResults.results.length) panel.append(empty('没有找到匹配的科目。换个关键词，或在「更改年度 / 学科」里加上其他学科。'));
    else {
      if (syllabusResults.total > syllabusResults.results.length) panel.append(E('p', 'caption', `共 ${syllabusResults.total} 条，显示前 ${syllabusResults.results.length} 条，请输入更具体的关键词。`));
      for (const row of syllabusResults.results) panel.append(syllabusRow(row));
    }
  }
  main.append(panel);
  if (state.courses.length) main.append(syllabusLinkedPanel());
}

function syllabusSetup() {
  const panel = E('section', 'panel');
  const prefs = syllabusOptions.prefs || {};
  let nendo = prefs.nendo || syllabusOptions.default_year;
  let faculty = prefs.faculty || '1';
  const chosen = new Set(prefs.departments || []);
  panel.append(E('h2', '', '先选年度和学科'), E('p', 'caption', '学校的检索接口按学科返回科目。选你所在的学科，再加上「一般教育」就能覆盖大部分课程。'));
  const form = E('form', 'syllabus-setup');
  const list = E('div', 'syllabus-departments');
  function drawDepartments() {
    list.replaceChildren();
    for (const d of syllabusOptions.departments.filter(d => d.nendo === nendo && d.faculty === faculty)) {
      const label = E('label', 'check'); const box = E('input'); box.type = 'checkbox'; box.checked = chosen.has(d.code);
      box.addEventListener('change', () => { box.checked ? chosen.add(d.code) : chosen.delete(d.code); });
      label.append(box, document.createTextNode(d.name)); list.append(label);
    }
  }
  const years = selectControl('年度', syllabusOptions.years.map(y => [y, y + ' 年度']), nendo, v => { nendo = v; drawDepartments(); });
  const faculties = [...new Map(syllabusOptions.faculties.filter(f => f.nendo === nendo).map(f => [f.code, f.name])).entries()];
  const facultySelect = selectControl('学部', faculties, faculty, v => { faculty = v; chosen.clear(); drawDepartments(); });
  const row = E('div', 'row wrap'); row.append(years, facultySelect);
  const save = E('button', 'button', '保存并开始查询'); save.type = 'submit';
  form.addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const result = await api('/api/syllabus/prefs', {nendo, faculty, departments: [...chosen]});
      syllabusOptions.prefs = result.prefs; syllabusEditing = false; syllabusResults = null;
      for (const key of Object.keys(syllabusSuggestions)) delete syllabusSuggestions[key];
      render();
    } catch (error) { toast(error.message); }
  });
  drawDepartments();
  form.append(row, list, save);
  if (syllabusOptions.prefs) form.append(button('取消', () => { syllabusEditing = false; render(); }, 'button quiet'));
  panel.append(form);
  return panel;
}

async function searchSyllabus(value) {
  const query = value.trim();
  if (!query || syllabusSearching) return;
  syllabusSearching = true; render();
  try { syllabusResults = await api('/api/syllabus/search', {query}); }
  catch (error) { toast(error.message); }
  finally { syllabusSearching = false; if (route === 'syllabus') render(); }
}

function syllabusRow(row, course) {
  const line = E('div', 'resource-row syllabus-result');
  const body = E('div', 'task-body');
  body.append(button(row.title + (row.note ? ' ' + row.note : ''), () => openSyllabus(row), 'task-title'));
  const meta = E('div', 'task-meta');
  meta.append(pill(row.code), E('span', '', row.teacher));
  for (const text of [row.term, row.slots.join(' / '), row.grade ? row.grade + ' 年' : '', row.department]) if (text) meta.append(E('span', 'muted', text));
  body.append(meta);
  const actions = E('div', 'row');
  if (course) actions.append(button('关联到这门课', () => linkSyllabus(course, row), 'button secondary'));
  actions.append(link('官网 ↗', row.url, 'button quiet'));
  line.append(body, actions);
  return line;
}

async function syllabusDetail(row) {
  const key = row.code + '@' + row.nendo;
  if (!syllabusDetails[key]) syllabusDetails[key] = await api('/api/syllabus/detail', {nendo: row.nendo, faculty: row.faculty || '1', code: row.code});
  return syllabusDetails[key];
}

function syllabusBody(target, detail) {
  const meta = E('div', 'row wrap');
  meta.append(pill(detail.code), E('span', 'muted', detail.teachers.join('、')));
  if (detail.credits) meta.append(pill(detail.credits + ' 単位'));
  target.append(meta);
  if (detail.subtitle) target.append(E('p', '', detail.subtitle));
  for (const section of detail.sections) target.append(E('div', 'detail-label', section.title), E('div', 'preline', section.text));
  for (const [title, books, note] of [['教科書', detail.textbooks, detail.textbook_note], ['参考書', detail.references, detail.reference_note]]) {
    if (!books.length && !note) continue;
    target.append(E('div', 'detail-label', title));
    const list = E('ul'); for (const book of books) list.append(E('li', '', book)); target.append(list);
    if (note) target.append(E('p', 'caption', note));
  }
  if (detail.office_hours.length) target.append(E('div', 'detail-label', 'オフィスアワー'), E('div', 'preline', detail.office_hours.join('\n')));
  if (detail.schedule.length) {
    target.append(E('div', 'detail-label', '授業計画'));
    const table = E('div', 'syllabus-schedule');
    for (const row of detail.schedule) {
      const item = E('div', 'syllabus-week');
      item.append(E('strong', '', `${row.online ? 'オンデマンド ' + row.number : '第 ' + row.number + ' 回'}${row.date ? ' · ' + row.date.slice(5).replace('-', '/') + (row.online ? ' 起' : '') : ''}`),
        E('div', 'preline', row.content));
      if (row.study) item.append(E('div', 'caption preline', row.study));
      table.append(item);
    }
    target.append(table);
  }
  target.append(E('div', 'detail-label', '原文'), link('在学校官网打开 ↗', detail.url, 'button secondary'));
}

async function openSyllabus(row) {
  const body = document.querySelector('#detailBody');
  body.replaceChildren(E('div', 'eyebrow', 'SYLLABUS'), E('h2', '', row.title), E('p', 'caption', '正在从学校官网读取…'));
  if (!dialog.open) dialog.showModal();
  try {
    const detail = await syllabusDetail(row);
    body.replaceChildren(E('div', 'eyebrow', 'SYLLABUS · ' + detail.nendo), E('h2', '', detail.title));
    syllabusBody(body, detail);
    if (state.courses.length) {
      const pick = selectControl('关联到已同步课程', [['', '关联到我的课程…'], ...state.courses.map(c => [c.id, c.name + ' · ' + sourceName(c.source)])], '', async value => {
        const course = state.courses.find(c => c.id === value);
        if (course) await linkSyllabus(course, row);
      });
      body.append(E('div', 'detail-label', '关联后学习助手可以引用这份大纲'), pick);
    }
  } catch (error) { body.append(E('p', '', error.message)); }
}

async function linkSyllabus(course, row) {
  try {
    await api('/api/syllabus/link', row ? {course: course.id, code: row.code, nendo: row.nendo, faculty: row.faculty || '1'} : {course: course.id});
    delete syllabusSuggestions[course.id];
    await refresh(true);
    toast(row ? `已把「${row.title}」的大纲关联到 ${course.name}。学习助手回答这门课时会引用它。` : '已取消关联。');
  } catch (error) { toast(error.message); }
}

function syllabusLinkedPanel() {
  const panel = E('section', 'panel');
  panel.append(E('h2', '', '已关联的课程'));
  const links = state.syllabus_links || {};
  let count = 0;
  for (const course of state.courses) {
    const linked = links[course.id];
    if (!linked) continue;
    count++;
    const row = E('div', 'resource-row');
    const body = E('div', 'task-body');
    body.append(button(course.name, () => { courseId = course.id; courseTab = 'syllabus'; navigate('courses'); }, 'task-title'),
      E('div', 'task-meta', '→ ' + linked.title + ' · ' + linked.code));
    row.append(body, button('取消关联', () => linkSyllabus(course, null), 'button quiet'));
    panel.append(row);
  }
  if (!count) panel.append(empty('还没有关联。进入「课程与资料」里的任意一门课，打开「课程大纲」标签，系统会按课程名自动推荐。'));
  return panel;
}

/* Course page tab: show the linked syllabus, or suggest matches from the course name. */
function renderCourseSyllabus(content, course) {
  if (demo) return content.append(empty('演示模式不查询学校网站。'));
  const linked = (state.syllabus_links || {})[course.id];
  if (linked) {
    const key = linked.code + '@' + linked.nendo;
    const head = E('div', 'row spread');
    head.append(E('h2', '', linked.title), button('取消关联', () => linkSyllabus(course, null), 'button quiet'));
    content.append(head);
    const detail = syllabusDetails[key];
    if (detail) syllabusBody(content, detail);
    else {
      content.append(E('p', 'caption', '正在从学校官网读取…'));
      syllabusDetail(linked).then(() => { if (courseId === course.id && courseTab === 'syllabus') render(); }, error => toast(error.message));
    }
    return;
  }
  const entry = syllabusSuggestions[course.id];
  if (!entry) {
    syllabusSuggestions[course.id] = {loading: true};
    api('/api/syllabus/suggest', {course: course.id})
      .then(result => { syllabusSuggestions[course.id] = result; }, error => { syllabusSuggestions[course.id] = {error: error.message}; })
      .finally(() => { if (courseId === course.id && courseTab === 'syllabus') render(); });
    return content.append(empty('正在按课程名匹配学校シラバス…'));
  }
  if (entry.loading) return content.append(empty('正在按课程名匹配学校シラバス…'));
  if (entry.error) {
    content.append(empty(entry.error));
    return content.append(button('去「课程大纲」设置 →', () => navigate('syllabus'), 'button secondary'));
  }
  content.append(E('h2', '', '这门课还没关联大纲'));
  if (entry.suggestions.length) {
    content.append(E('p', 'caption', '按课程名推荐，确认是同一门课再关联（同名课可能有多个班，注意看老师和时间）。'));
    for (const row of entry.suggestions) content.append(syllabusRow(row, course));
  } else content.append(empty('没能按课程名自动匹配。'));
  content.append(button('手动搜索 →', () => { syllabusQuery = course.name.replace(/^[\d\s_\-]+/, '').slice(0, 40); navigate('syllabus'); searchSyllabus(syllabusQuery); }, 'button quiet'));
}
