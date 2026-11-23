/* Read enrolled course pages and Canvas's published, same-origin assignments feed. */
(() => {
  'use strict';
  const compact = value => String(value || '').replace(/\s+/g, ' ').trim();
  const text = node => compact(node?.innerText || node?.textContent || '');
  function url(value, base) {
    try { const u = new URL(value, base); return ['https:', 'http:'].includes(u.protocol) && !u.username ? u : null; }
    catch { return null; }
  }
  function timestamp(year, month, day, hour, minute, offset) {
    const date = new Date(Date.UTC(year, month - 1, day, hour, minute));
    if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day || hour > 23 || minute > 59) return null;
    return new Date(date.getTime() - offset * 60000).toISOString();
  }
  function parseDue(value, offset = 540, observed = Date.now()) {
    const original = compact(value);
    if (!original || /^(?:no due date|no deadline|期限なし|期限なしです|期限未設定|截止日期未设置|无截止日期)$/i.test(original))
      return {due_at: null, due_text: original, date_uncertain: false};
    let match = original.match(/\b(20\d\d)-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})\b/);
    if (match) {
      const iso = match[0];
      const valid = timestamp(+match[1], +match[2], +match[3], +match[4], +match[5], 0);
      if (valid && Number.isFinite(Date.parse(iso))) return {due_at: new Date(iso).toISOString(), due_text: original, date_uncertain: false};
    }
    const zone = original.match(/\b(JST|UTC|GMT|PST|PDT|EST|EDT)\b/i);
    if (zone) offset = {JST:540,UTC:0,GMT:0,PST:-480,PDT:-420,EST:-300,EDT:-240}[zone[1].toUpperCase()];
    const relative=original.match(/(明天|明日|今天|今日|tomorrow\b|today\b)[^\d]*(\d{1,2})[:：](\d{2})\s*(am|pm)?/i);
    if(relative && !/午[前後]|上午|下午/.test(original)){
      const day=new Date(observed+offset*60000);
      if(/明天|明日|tomorrow/i.test(relative[1]))day.setUTCDate(day.getUTCDate()+1);
      let hour=+relative[2];
      if(relative[4] && hour>=1 && hour<=12)hour=hour%12+(/pm/i.test(relative[4])?12:0);
      else if(relative[4])return {due_at:null,due_text:original,date_uncertain:true};
      const due=timestamp(day.getUTCFullYear(),day.getUTCMonth()+1,day.getUTCDate(),hour,+relative[3],offset);
      if(due)return {due_at:due,due_text:original,date_uncertain:false};
    }
    match = original.match(/(20\d\d)[年/.-]\s*(\d{1,2})[月/.-]\s*(\d{1,2})(?:日)?[^\d]*?(?:(午前|午後|上午|下午)\s*)?(\d{1,2})[:：](\d{2})\s*(am|pm)?/i);
    let components;
    if (match) components = [+match[1], +match[2], +match[3], +match[5], +match[6], match[4] || match[7]];
    else {
      const months = {jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};
      match = original.match(/\b(Jan\w*|Feb\w*|Mar\w*|Apr\w*|May|Jun\w*|Jul\w*|Aug\w*|Sep\w*|Oct\w*|Nov\w*|Dec\w*)\s+(\d{1,2}),?\s+(20\d\d).*?(\d{1,2})[:：](\d{2})\s*(am|pm)?/i);
      if (match) components = [+match[3], months[match[1].slice(0,3).toLowerCase()], +match[2], +match[4], +match[5], match[6]];
    }
    if (components) {
      let [year, month, day, hour, minute, period] = components;
      if (period) {
        if (hour < 1 || hour > 12) return {due_at:null,due_text:original,date_uncertain:true};
        hour = hour % 12 + (/pm|午後|下午/i.test(period) ? 12 : 0);
      }
      const due = timestamp(year, month, day, hour, minute, offset);
      if (due) return {due_at:due,due_text:original,date_uncertain:false};
    }
    // Missing years or clock times remain visible for confirmation; never guess a day.
    return {due_at:null,due_text:original,date_uncertain:true};
  }
  function dueFor(node, offset) {
    const dueLabel=/due|締[め切]*|提出期限|期限|截止|到期/i;
    const nodes = [...node.querySelectorAll('[data-due-at], [data-due-date], .due-date, .due_date, .assignment-date-due, [data-testid*="due"], .assignment_dates li, .student-assignment-overview li')].filter(n=>!n.matches('.assignment_dates li,.student-assignment-overview li')||dueLabel.test(text(n)));
    for (const n of node.querySelectorAll('[aria-label], time[datetime], .display_date')) {
      if (dueLabel.test(n.getAttribute('aria-label') || n.parentElement?.textContent || '')) nodes.push(n);
    }
    let firstFallback;
    for (const n of nodes) {
      const dateNodes=[n,...n.querySelectorAll('time,.display_date,.date,[data-due-at],[data-datetime],[data-html-tooltip-title]')];
      const values=dateNodes.flatMap(child=>['data-due-at','data-due-date','datetime','data-datetime','title','data-tooltip','data-html-tooltip-title','aria-label'].map(name=>child.getAttribute(name))).concat(text(n));
      let fallback;
      for (const value of values.filter(Boolean)) { const parsed = parseDue(value, offset); if(parsed.due_at)return parsed; fallback ||= parsed; }
      firstFallback ||= fallback;
    }
    const line = (node.innerText || node.textContent || '').split('\n').map(compact).find(line => /^(?:Due\b|締[め切]*|提出期限|期限|截止|到期)/i.test(line));
    return firstFallback || parseDue(line || '', offset);
  }
  function identity(doc, source) {
    if(source === 'canvas') {
      const form = doc.querySelector('form[action*="/users/"], form[id^="edit_user_"]');
      const id = form?.getAttribute('action')?.match(/\/users\/(\d+)/)?.[1] || form?.id?.match(/^edit_user_(\d+)/)?.[1];
      const username = doc.querySelector('#user_short_name, input[name="user[short_name]"]')?.value;
      const label = doc.querySelector('#user_name, input[name="user[name]"]')?.value || text(doc.querySelector('.full_name, h1'));
      if(id || username) return {key:'canvas:'+(id || username),label:label || 'Canvas 账号'};
    } else {
      const nodes = doc.querySelectorAll('a[href*="accounts.google.com"][aria-label], button[aria-label*="@"], [data-profile-identifier]');
      for(const node of nodes) {
        const value = node.getAttribute('data-profile-identifier') || node.getAttribute('aria-label') || '';
        const email = value.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)?.[0];
        if(email) return {key:'classroom:'+email.toLowerCase(),label:email};
      }
    }
    return null;
  }
  function attachments(node, base) {
    const result = [], seen = new Set();
    for(const a of node.querySelectorAll('a[href]')) {
      const target = url(a.getAttribute('href'), base); if(!target)continue;
      if(a.getAttribute('href').startsWith('#') || seen.has(target.href))continue;
      if(target.origin === new URL(base).origin && !/\/files\/|\/attachments\/|\/d\//.test(target.pathname))continue;
      seen.add(target.href); result.push({title:text(a)||a.getAttribute('title')||'查看附件',url:target.href});
    }
    return result.slice(0,100);
  }
  function submission(node) {
    const status = text(node.querySelector('.submission_status, #submission_details, [data-testid="submission-status"], [data-submission-state]')) || text(node).slice(-1500);
    if(/(?:not turned in|unsubmitted|未提出|未提交|未完成|missing)/i.test(status))return 'pending';
    if(/(?:turned in|submitted|提出済み|提出済|已提交|已上交)/i.test(status))return 'submitted';
    if(/(?:returned|返却済|已退回)/i.test(status))return 'returned';
    return 'unknown';
  }
  function collect(doc, address, context = {}) {
    const location = new URL(address), source = location.hostname === 'nu.instructure.com' ? 'canvas' : 'classroom';
    const linkBase = url(doc.baseURI, address)?.href || address;
    const main = (source==='classroom' ? [...doc.querySelectorAll('main,[role="main"]')].find(n=>n.querySelector('[data-stream-item-id],h1,[role="heading"],article')) : doc.querySelector('main, #content, [role="main"]')) || doc.body;
    const result = {source, origin:location.origin, identity:identity(doc,source), courses:[], items:[], resources:[], links:[], warnings:[], recognized:false, login:false};
    if(!['nu.instructure.com','classroom.google.com'].includes(location.hostname))return result;
    // Account settings can legitimately contain change-password fields. Only a
    // login form (or an unidentifiable password screen) means the session expired.
    result.login = !!doc.querySelector('form#login_form, form[action="/login"], form[action="/login/canvas"], .ic-Login') || /\/(?:login|signin)(?:\/|$)/.test(location.pathname) ||
      (!!doc.querySelector('input[type="password"]') && !result.identity && !/^\/courses\//.test(location.pathname));
    if(result.login)return result;
    const courseId = source === 'canvas' ? location.pathname.match(/^\/courses\/(\d+)/)?.[1] : location.pathname.match(/^\/(?:u\/\d+\/)?(?:c|w)\/([^/]+)/)?.[1];
    const prefix = location.pathname.match(/^\/u\/\d+/)?.[0] || '';
    const courseURL = id => source==='canvas' ? `${location.origin}/courses/${id}` : `${location.origin}${prefix}/c/${id}`;
    const courseName = context.course_name || text(doc.querySelector('#breadcrumbs li:nth-last-child(2), [data-testid="course-name"], [data-course-name], header h1, main h1')) || '未命名课程';
    const baseRecord = {source,course_id:courseId,course:courseName};
    const links = new Map();
    const enqueue = (target, kind, id = courseId, name = courseName) => {
      const candidate = url(target,address); if(!candidate || candidate.origin!==location.origin)return;
      if(!/^\/(?:courses(?:[/?]|$)|(?:u\/\d+\/)?(?:h(?:[/?]|$)|[cw]\/))/.test(candidate.pathname))return;
      candidate.hash='';
      if(!/(?:[?&]page=|\/courses$)/.test(candidate.href))candidate.search='';
      links.set(candidate.href,{url:candidate.href,kind,course_id:id||'',course_name:name});
    };
    if(result.identity)result.recognized=true;
    if(courseId)result.courses.push({id:`${source}:${courseId}`,source,course_id:courseId,name:courseName,url:courseURL(courseId)});
    const home=source==='classroom' && !courseId;
    const pageLinks=source==='classroom'?[...doc.querySelectorAll('a[href]')]:[...main.querySelectorAll('a[href]'),...doc.querySelectorAll('#section-tabs a[href]')];
    if(home){
      for(const a of pageLinks){
        const target=url(a.getAttribute('href'),linkBase);
        if(target?.origin===location.origin && /^\/(?:u\/\d+\/)?h\/st\/?$/.test(target.pathname)&&target.pathname!==location.pathname)
          enqueue(target.href,'student-home');
      }
    }
    for(const a of pageLinks) {
      const target=url(a.getAttribute('href'),linkBase);if(!target || target.origin!==location.origin)continue;
      const targetId = source==='canvas' ? target.pathname.match(/^\/courses\/(\d+)(?:\/|$)/)?.[1] : target.pathname.match(/^\/(?:u\/\d+\/)?(?:c|w)\/([^/]+)/)?.[1];
      if(!targetId)continue;
      const title=text(a) || a.getAttribute('title') || '';
      if(!courseId && title) {
        if(home && /\/sp\/[\w-]+\/all\/default\/?$/.test(target.pathname)){
          const card=a.closest('li,[role="listitem"],article');
          const courseLabel=text(card?.querySelector('h2,h3,[role="heading"]'));
          enqueue(target.href,'my-work',targetId,courseLabel);
          continue;
        }
        if(home && /\/(?:a|sa)\/[^/]+\/details\/?$/.test(target.pathname)){
          enqueue(target.href,'assignment',targetId,'');
          continue;
        }
        if(home && !/^\/(?:u\/\d+\/)?c\/[\w-]+\/?$/.test(target.pathname))continue;
        const container=a.closest('[data-course-id], [role="listitem"], tr, article, li');
        const name=text(container?.querySelector('h2,h3,[data-testid="course-name"]')) || title.split('\n')[0];
        result.courses.push({source,course_id:targetId,name:name.slice(0,300),url:courseURL(targetId)});
        enqueue(courseURL(targetId),'course',targetId,name);
      } else if(targetId===courseId) {
        if(source==='classroom' && /^\/(?:u\/\d+\/)?w\/[\w-]+\/t\/all\/?$/.test(target.pathname))enqueue(target.href,'coursework');
        if(source==='canvas' && /^\/courses\/\d+\/modules\/items\/\d+\/?$/.test(target.pathname)) {
          const row=a.closest('.context_module_item,[data-module-item-id]');
          const assignmentId=String(row?.className||'').match(/(?:^|\s)Assignment_(\d+)(?:\s|$)/)?.[1];
          const fileId=String(row?.className||'').match(/(?:^|\s)Attachment_(\d+)(?:\s|$)/)?.[1];
          if(assignmentId){
            const canonical=courseURL(courseId)+'/assignments/'+assignmentId;
            result.items.push({...baseRecord,title:title||'未命名作业',url:canonical,description:'',attachments:[],detail_level:0,status:'unknown',...dueFor(row,context.offset)});
            enqueue(canonical,'assignment');
          }else if(fileId){
            result.resources.push({...baseRecord,kind:'file',title:title||'课程文件',url:courseURL(courseId)+'/files/'+fileId,description:'',attachments:[],group:'学习模块',detail_level:0});
          }else if(row?.classList.contains('wiki_page')||row?.classList.contains('discussion')||
              row?.classList.contains('quiz'))enqueue(target.href,'module');
          else if(title)result.resources.push({...baseRecord,kind:'module',title,url:target.origin+target.pathname,
            description:'',attachments:[],group:'学习模块',detail_level:0});
        }
        if(source==='canvas' && /^\/courses\/\d+\/(?:assignments|announcements|modules|files|pages)(?:\/[^/]+)?\/?$/.test(target.pathname)) {
          if(/\/(?:files)\//.test(target.pathname)) {
            if(title)result.resources.push({...baseRecord,kind:'file',title,url:target.origin+target.pathname,description:'',attachments:[],group:context.kind==='module'?'学习单元':''});
          } else enqueue(target.href, /\/announcements/.test(target.pathname)?'announcement':context.kind || 'material');
        }
        if(source==='classroom' && /\/(?:w\/all|(?:sa|[amp])\/[^/]+(?:\/details)?)\/?$/.test(target.pathname))enqueue(target.href,/\/(?:sa|a)\//.test(target.pathname)?'assignment':/\/p\//.test(target.pathname)?'announcement':'material');
      }
      const assignment = source==='canvas' ? target.pathname.match(/^\/courses\/\d+\/assignments\/(\d+)\/?$/) : target.pathname.match(/\/c\/[^/]+\/(?:sa|a)\/([^/]+)\/details\/?$/);
      if(assignment && targetId===courseId && title) {
        const row=a.closest('.assignment, .ig-row, [data-stream-item-id], [role="listitem"], article, li') || a.parentElement;
        result.items.push({...baseRecord,title,url:target.origin+target.pathname,description:'',attachments:[],detail_level:0,status:'unknown',...dueFor(row,context.offset)});
        enqueue(target.href,'assignment');
      }
      if(source==='canvas' && /\/discussion_topics\/\d+/.test(target.pathname))enqueue(target.href,'announcement');
      if(a.matches('[rel="next"], .next_page, [aria-label="Next page"], [aria-label="次のページ"]'))enqueue(target.href,context.kind);
    }
    if(courseId) {
      const isAssignment = source==='canvas' ? /^\/courses\/\d+\/(?:assignments|quizzes)\/\d+\/?$/.test(location.pathname) : /\/c\/[^/]+\/(?:sa|a)\/[^/]+\/details\/?$/.test(location.pathname);
      const isMaterial = source==='canvas' ? /\/pages\/[^/]+|\/discussion_topics\/\d+/.test(location.pathname) : /\/c\/[^/]+\/[mp]\/[^/]+(?:\/details)?\/?$/.test(location.pathname);
      const heading = text(main.querySelector('h1, [data-testid="assignment-title"], [role="heading"][aria-level="1"], h2'));
      if((isAssignment || isMaterial) && heading) {
        const instructions = main.querySelector('.description.user_content, .user_content, [data-testid="assignment-description"], [data-field="description"], .pco8Kc, .OjOEXb');
        const fallback=(main.innerText || main.textContent || '').split(/Class comments|クラスのコメント|班级评论|Private comments|限定公開のコメント/i)[0];
        const record={...baseRecord,title:heading,url:location.origin+location.pathname,
          description:(instructions?.innerText || instructions?.textContent || fallback).trim().slice(0,30000),
          attachments:attachments(instructions || main,address),detail_level:1};
        if(isAssignment)result.items.push({...record,status:submission(main),
          text_entry:!!main.querySelector('#submit_online_text_entry_form,[data-testid="text-entry"],textarea[name="submission[body]"]') ||
            (source==='classroom' && /\/sa\//.test(location.pathname) && !!main.querySelector('textarea[aria-label], [contenteditable="true"][aria-label]')),
          ...dueFor(main,context.offset)});
        else result.resources.push({...record,kind:/discussion_topics|\/p\//.test(location.pathname)?'announcement':'page',group:''});
        result.recognized=true;
      }
      if(source==='classroom' && /\/c\/[^/]+\/?$/.test(location.pathname) &&
        ![...links.values()].some(link=>link.kind==='coursework'||link.url.endsWith('/w/all')))
        enqueue(location.origin+prefix+'/w/'+courseId+'/t/all','coursework');
      if(source==='classroom' && /^\/(?:u\/\d+\/)?w\/[\w-]+\/t\/all\/?$/.test(location.pathname)){
        for(const row of doc.querySelectorAll('[data-stream-item-id]')){
          const id=row.getAttribute('data-stream-item-id');
          let itemKey;
          if(/^\d{1,22}$/.test(id))itemKey=btoa(id).replace(/=+$/,'');
          else if(/^[\w-]{3,40}$/.test(id)){
            try{if(/^\d{1,22}$/.test(atob(id)))itemKey=id;}catch{}
          }
          if(!itemKey)continue;
          const labels=[...row.querySelectorAll('[aria-label]')].map(n=>n.getAttribute('aria-label')).join(' ');
          const kind=/资料选项|教材のオプション|material options/i.test(labels)?'m':
            /作业选项|課題のオプション|assignment options/i.test(labels)?'a':null;
          const label=row.querySelector('h2,h3,[role="heading"],[role="button"][aria-expanded]');
          const title=(label?.innerText||label?.textContent||'').trim().split('\n')[0].trim();
          if(!kind || !title)continue;
          const target=courseURL(courseId)+'/'+kind+'/'+itemKey+'/details';
          if(kind==='a')result.items.push({...baseRecord,title,url:target,description:'',attachments:[],detail_level:0,status:'unknown',...dueFor(row,context.offset)});
          else result.resources.push({...baseRecord,kind:'material',title,url:target,description:'',attachments:[],group:'',detail_level:0});
          enqueue(target,kind==='a'?'assignment':'material');
        }
      }
      // Stream posts often have no separate link until expanded. Preserve their text as announcements.
      for(const row of main.querySelectorAll('[data-stream-item-id][data-announcement], [data-testid="announcement"]')) {
        const id=row.getAttribute('data-stream-item-id') || row.id;
        if(id)result.resources.push({...baseRecord,kind:'announcement',title:text(row.querySelector('h2,h3')) || text(row).slice(0,80),
          description:row.innerText || row.textContent,url:courseURL(courseId)+'#post-'+encodeURIComponent(id),attachments:attachments(row,address),detail_level:1,group:''});
      }
      if(main.querySelector('h1,h2,[data-stream-item-id],.assignment,.context_module,.ig-list'))result.recognized=true;
    } else if(result.courses.length)result.recognized=true;
    result.links=[...links.values()];
    for(const key of ['courses','items','resources'])result[key]=[...new Map(result[key].map(r=>[r.url,r])).values()];
    if(result.items.some(item=>item.date_uncertain))result.warnings.push('部分截止日期缺少年份、时刻或明确格式，已保留原文待确认。');
    result.diagnostics={path:location.pathname,title:doc.title||'',link_count:pageLinks.length,discovered:result.links.length,
      items:result.items.length,resources:result.resources.length,
      sample_routes:pageLinks.slice(0,24).map(a=>url(a.getAttribute('href'),address)?.pathname).filter(Boolean),
      date_nodes:[...main.querySelectorAll('.student-assignment-overview li,.assignment_dates li,.due-date,.display_date,time[datetime]')].slice(0,12).map(n=>({tag:n.tagName,class:n.className,
        text:text(n).slice(0,300),attributes:Object.fromEntries(['datetime','title','data-tooltip','data-html-tooltip-title','aria-label'].map(name=>[name,n.getAttribute(name)]).filter(([,v])=>v))}))};
    return result;
  }
  async function* canvasPages(pathname, query) {
    let next=new URL(pathname+'?per_page=100&'+query, location.origin);
    for (let page=0; next && page<20; page++) {
      if(next.origin!==location.origin || next.pathname!==pathname || next.username)throw new Error();
      const res=await fetch(next,{credentials:'same-origin',redirect:'error',headers:{Accept:'application/json'},signal:AbortSignal.timeout(6000)});
      if(!res.ok)throw new Error();
      const records=JSON.parse((await res.text()).replace(/^while\(1\);/,''));
      if(!Array.isArray(records))throw new Error();
      yield records;
      const following=(res.headers.get('Link')||'').match(/<([^>]+)>;\s*rel="next"/)?.[1];
      next=following?new URL(following,location.origin):null;
    }
    if(next)throw new Error();
  }
  async function canvasDeadlines(result) {
    // Called only from the user's own course index. Canvas controls visibility and due-date overrides.
    for (const course of result.courses) {
      if (!/^\d+$/.test(course.course_id)) continue;
      const pathname='/api/v1/courses/'+course.course_id+'/assignments';
      try {
        for await (const records of canvasPages(pathname,'include%5B%5D=submission')) {
          for (const record of records) {
            if (String(record.course_id)!==course.course_id || !/^\d+$/.test(String(record.id))) continue;
            const sourceURL=course.url+'/assignments/'+record.id;
            const doc=new DOMParser().parseFromString(record.description||'','text/html');
            doc.querySelectorAll('style,script').forEach(n=>n.remove());
            doc.querySelectorAll('p,li,div,br').forEach(n=>n.append('\n'));
            const sub=record.submission||{};
            const status=sub.excused?'excused':sub.submitted_at?'submitted':sub.workflow_state==='unsubmitted'?'pending':'unknown';
            result.items.push({course:course.name,course_id:course.course_id,title:record.name,url:sourceURL,
              description:doc.body.textContent.trim(),attachments:attachments(doc.body,sourceURL),detail_level:2,status,
              text_entry:Array.isArray(record.submission_types)&&record.submission_types.includes('online_text_entry'),
              ...parseDue(record.due_at)});
          }
        }
      } catch {
        result.warnings.push(course.name+'：无法完整读取 Canvas 作业列表，将继续检查课程网页。');
      }
    }
  }
  async function canvasModules(result, course) {
    const path='/api/v1/courses/'+course.course_id+'/modules';
    const addItems=(module,items)=>{
      for(const item of items){
        if(!/^\d+$/.test(String(item.id)) || ['SubHeader','Assignment','Quiz'].includes(item.type))continue;
        const canonical=url(item.html_url,location.origin);
        if(!canonical || canonical.origin!==location.origin || !canonical.pathname.startsWith('/courses/'+course.course_id+'/'))continue;
        const target=item.type==='File' && /^\d+$/.test(String(item.content_id))?course.url+'/files/'+item.content_id:canonical.origin+canonical.pathname;
        result.resources.push({source:'canvas',course_id:course.course_id,kind:item.type==='File'?'file':'module',
          title:item.title,url:target,description:'',attachments:[],group:module.name,detail_level:0});
      }
    };
    try {
      for await(const modules of canvasPages(path,'include%5B%5D=items')){
        for(const module of modules){
          if(Array.isArray(module.items) && module.items.length >= (module.items_count || 0))addItems(module,module.items);
          else if(/^\d+$/.test(String(module.id)))for await(const items of canvasPages(path+'/'+module.id+'/items',''))addItems(module,items);
        }
      }
    }catch{result.warnings.push(course.name+'：部分模块资料需要从原课程查看。');}
  }
  async function prepare() {
    const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
    const main=location.hostname==='classroom.google.com'?document.body:(document.querySelector('main,#content,[role="main"]') || document.body);
    let changed=false;
    for(let pass=0;pass<5;pass++) {
      const expand=[...main.querySelectorAll('button[aria-expanded="false"], [role="button"][aria-expanded="false"]')].filter(n=>n.closest('[data-stream-item-id],.assignment,[role="listitem"]'));
      const more=[...main.querySelectorAll('button,[role="button"]')].filter(n=>/^(?:show more|load more|もっと見る|さらに表示|显示更多|加载更多)$/i.test(text(n)));
      if(!expand.length&&!more.length)break;
      for(const node of [...expand,...more].slice(0,40)){node.click();changed=true;}
      await sleep(500);
    }
    if(changed)await sleep(300);
  }
  globalThis.StudyDockDOM={collect,parseDue,identity};
  if(globalThis.chrome?.runtime?.onMessage)chrome.runtime.onMessage.addListener((message,sender,respond)=>{
    if(message.type!=='study-dock-collect')return;
    (async()=>{
      let result,previous='',stable=0;
      const googleHome=location.hostname==='classroom.google.com' && /^\/(?:u\/\d+\/)?h(?:\/st)?\/?$/.test(location.pathname);
      if(message.identityOnly && googleHome){
        for(let i=0;i<24;i++){
          const who=identity(document,'classroom');
          if(who)return {identity:who,source:'classroom',origin:location.origin};
          await new Promise(r=>setTimeout(r,250));
        }
      }
      if(message.expectedIdentity && identity(document,'classroom')?.key!==message.expectedIdentity)return {mismatch:true};
      for(let attempt=0;attempt<(googleHome?48:18);attempt++){
        await new Promise(r=>setTimeout(r,250));if(!googleHome)await prepare();result=collect(document,location.href,message.context);
        if(result.login)break;
        const profile=result.source==='canvas'&&location.pathname==='/profile/settings';
        const discovered=result.links.length+result.items.length+result.resources.length;
        const empty=/no classes|no assignments|no classwork|クラスはありません|課題はありません|尚无课程|暂无作业|没有课业|尚未发布任何作业/i.test(document.querySelector('main,#content,[role="main"]')?.textContent||'');
        const fingerprint=JSON.stringify([result.courses.length,discovered,result.items.map(i=>[i.url,i.due_at,i.due_text])]);
        stable=fingerprint===previous?stable+1:0;previous=fingerprint;
        const meaningful=result.source==='classroom' && !googleHome ? result.items.length+result.resources.length+
          result.links.filter(l=>/\/(?:sa|a|m|p)\/[^/]+(?:\/details)?\/?$/.test(new URL(l.url).pathname)).length : discovered;
        if(stable>=1&&((profile&&result.identity)||(result.recognized&&((googleHome?result.courses.length:meaningful)>0||empty))))break;
      }
      if(!result.links.length&&!result.items.length&&!result.resources.length&&!/\/profile\/settings$/.test(location.pathname))result.warnings.push('该页面未发现可读取的作业或资料入口，不能据此认定没有作业。');
      if (result.source==='canvas' && location.pathname==='/courses' && !result.login)
        await canvasDeadlines(result);
      if (result.source==='canvas' && message.context.kind==='course' && result.courses[0] && !result.login)
        await canvasModules(result,result.courses[0]);
      return result;
    })().then(respond,error=>respond({error:error.message}));
    return true;
  });
})();
