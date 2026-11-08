(function () {
  'use strict';
  // confirmation before destructive actions (forms carrying data-confirm)
  [].forEach.call(document.querySelectorAll('form[data-confirm]'), function (d) {
    d.addEventListener('submit', function (e) { if (!window.confirm(d.getAttribute('data-confirm'))) e.preventDefault(); });
  });
  // no double submit (double tap on an iPad)
  [].forEach.call(document.querySelectorAll('form'), function (f) {
    f.addEventListener('submit', function (e) {
      if (e.defaultPrevented) return;
      if (f.dataset.sent) { e.preventDefault(); return; }
      f.dataset.sent = '1';
      setTimeout(function () { delete f.dataset.sent; }, 8000);
    });
  });
  // selects that reload the page with a new value (appointment day)
  [].forEach.call(document.querySelectorAll('select[data-autosubmit]'), function (s) {
    s.addEventListener('change', function () { s.form.submit(); });
  });
  // the queue page refreshes itself every 30 seconds while nobody is typing
  var rq = document.querySelector('[data-refresh]');
  if (rq) {
    var last = Date.now();
    document.addEventListener('input', function () { last = Date.now(); });
    setInterval(function () {
      var a = document.activeElement;
      var typing = a && /INPUT|TEXTAREA|SELECT/.test(a.tagName);
      if (!typing && Date.now() - last > 20000 && !document.querySelector('details[open].keep')) window.location.reload();
    }, +rq.getAttribute('data-refresh') * 1000);
  }
  // after opening the ready-made email, record on the ticket that the employee was told (best effort)
  [].forEach.call(document.querySelectorAll('a[data-notify]'), function (lnk) {
    lnk.addEventListener('click', function () {
      var tokEl = document.querySelector('input[name=csrf_token]');
      if (!tokEl || !window.fetch) return;
      var body = new URLSearchParams({ csrf_token: tokEl.value, action: 'notified' });
      setTimeout(function () {
        fetch(lnk.getAttribute('data-notify'), { method: 'POST', body: body, credentials: 'same-origin', redirect: 'manual' });
      }, 300);
    });
  });
  // action tabs on the ticket page (without JS every pane stays visible, one under the other)
  var tabs = [].slice.call(document.querySelectorAll('[role=tab]'));
  if (tabs.length) {
    var show = function (tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab, pane = document.getElementById(t.getAttribute('aria-controls'));
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
        if (pane) pane.hidden = !on;
      });
      if (focus) tab.focus();
    };
    tabs.forEach(function (t, i) {
      t.addEventListener('click', function () { show(t, false); });
      t.addEventListener('keydown', function (e) {
        var k = e.key, n = null;
        if (k === 'ArrowLeft') n = tabs[(i + 1) % tabs.length];       // RTL: left = next
        if (k === 'ArrowRight') n = tabs[(i - 1 + tabs.length) % tabs.length];
        if (k === 'Home') n = tabs[0];
        if (k === 'End') n = tabs[tabs.length - 1];
        if (n) { e.preventDefault(); show(n, true); }
      });
    });
    var first = tabs.filter(function (t) { return t.getAttribute('aria-selected') === 'true'; })[0] || tabs[0];
    if (location.hash === '#appt' && document.getElementById('tab-appt')) first = document.getElementById('tab-appt');
    // remember the open tab in the address (survives the queue page's auto-refresh)
    var h = location.hash.slice(1);
    tabs.forEach(function (t) {
      var pane = document.getElementById(t.getAttribute('aria-controls'));
      var anchors = ((pane && pane.getAttribute('data-anchors')) || '').split(' ');
      if (h && (t.getAttribute('data-hash') === h || anchors.indexOf(h) >= 0)) first = t;
      if (t.getAttribute('data-hash')) t.addEventListener('click', function () {
        if (history.replaceState) history.replaceState(null, '', '#' + t.getAttribute('data-hash'));
      });
    });
    show(first, false);
    if (location.hash === '#appt') { var act = document.getElementById('act'); if (act) act.scrollIntoView(); }
  }
  // checkboxes that apply a filter right away ("my tickets only")
  [].forEach.call(document.querySelectorAll('input[data-autosubmit-cb]'), function (c) {
    c.addEventListener('change', function () { c.form.submit(); });
  });
  // "+ add" buttons open the folded add form
  [].forEach.call(document.querySelectorAll('[data-open]'), function (b) {
    b.addEventListener('click', function (e) {
      var d = document.getElementById(b.getAttribute('data-open'));
      if (!d) return;
      e.preventDefault(); d.open = true; d.scrollIntoView({ block: 'start' });
      var f = d.querySelector('input:not([type=hidden])'); if (f) f.focus({ preventScroll: true });
    });
  });
  if (location.hash === '#add') { var ad = document.getElementById('add'); if (ad) ad.open = true; }
  // copy the suggested password
  [].forEach.call(document.querySelectorAll('[data-copy]'), function (b) {
    b.addEventListener('click', function () {
      var inp = document.getElementById(b.getAttribute('data-copy')); if (!inp) return;
      inp.select();
      var done = function () { var t = b.textContent; b.textContent = 'تم النسخ'; setTimeout(function () { b.textContent = t; }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(inp.value).then(done, function () { document.execCommand('copy'); done(); });
      else { document.execCommand('copy'); done(); }
    });
  });
  // ready-made replies: insert into the reply box with the employee's name and ticket number filled in
  var tpl = document.getElementById('tpl'), reply = document.getElementById('reply');
  if (tpl && reply) {
    tpl.addEventListener('change', function () {
      var opt = tpl.options[tpl.selectedIndex], body = opt && opt.getAttribute('data-body');
      if (!body) return;
      var name = tpl.getAttribute('data-name') || '';
      body = body.replace(/ ?\{الاسم\}/g, name ? ' ' + name : '').replace(/\{رقم_التذكرة\}/g, tpl.getAttribute('data-ref') || '');
      if (reply.value.trim() && !window.confirm('استبدال النص المكتوب بالرد الجاهز؟')) { tpl.value = ''; return; }
      reply.value = body; reply.dispatchEvent(new Event('input'));
      var used = document.getElementById('tpl_used'); if (used) used.value = tpl.value;
      tpl.value = ''; reply.focus();
    });
  }
  // drafts: what is typed in a reply or note is kept in this browser until it is sent
  [].forEach.call(document.querySelectorAll('textarea[data-draft]'), function (ta) {
    var key = 'shq-draft-' + ta.getAttribute('data-draft'), orig = ta.value, store = null;
    try { store = window.localStorage; } catch (e) { store = null; }
    if (!store) return;
    try {
      var saved = store.getItem(key);
      if (saved && saved !== orig) {
        ta.value = saved;
        var note = ta.parentNode.querySelector('.draft-note'); if (note) note.hidden = false;
      }
    } catch (e) {}
    var tmr;
    ta.addEventListener('input', function () {
      clearTimeout(tmr);
      tmr = setTimeout(function () { try { if (ta.value && ta.value !== orig) store.setItem(key, ta.value); else store.removeItem(key); } catch (e) {} }, 400);
    });
    if (ta.form) ta.form.addEventListener('submit', function () { try { store.removeItem(key); } catch (e) {} });
  });
})();
