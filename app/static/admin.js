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
    show(first, false);
    if (location.hash === '#appt') { var act = document.getElementById('act'); if (act) act.scrollIntoView(); }
  }
})();
