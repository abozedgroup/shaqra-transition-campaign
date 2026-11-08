(function () {
  'use strict';
  var f = document.getElementById('f');
  if (!f) return;
  var AR = '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹';
  function digits(s) {
    return s.replace(/[٠-٩۰-۹]/g, function (c) { return String(AR.indexOf(c) % 10); }).replace(/\s+/g, '');
  }
  // same rules as the server (app.py validate_ticket); messages are rendered by the server in the page language
  var anonTypes = (f.getAttribute('data-anon-types') || '').split(',');
  var anonBox = document.getElementById('anonbox'), anonChk = f.elements.anonymous;
  function curType() { var r = f.querySelector('input[name=req_type]:checked'); return r ? r.value : ''; }
  function isAnon() { return !!(anonChk && anonChk.checked && anonTypes.indexOf(curType()) >= 0); }
  // personal fields are not needed (and not sent) when the employee chooses not to share them
  var personal = { name: 1, emp_no: 1, job_cat: 1, email: 1, mobile: 1, facility: 1 };
  function syncAnon() {
    var allowed = anonTypes.indexOf(curType()) >= 0;
    if (anonBox) anonBox.classList.toggle('off', !allowed);
    var ab = document.getElementById('apptbox');
    if (ab) ab.classList.toggle('off', allowed || !curType());
    f.classList.toggle('anon', isAnon());
    if (isAnon()) Object.keys(personal).forEach(function (n) {
      var g = document.getElementById('g-' + n); if (g) g.classList.remove('bad');
    });
  }
  [].forEach.call(f.querySelectorAll('input[name=req_type]'), function (r) { r.addEventListener('change', syncAnon); });
  if (anonChk) anonChk.addEventListener('change', syncAnon);
  var rules = {
    req_type: function () { return !!f.querySelector('input[name=req_type]:checked'); },
    topic: function (v) { return v !== ''; },
    photos: function () {
      var inp = f.elements.photos, er = document.getElementById('e-photos');
      if (!inp || !inp.files) return true;
      var fs = [].slice.call(inp.files), msg = '';
      if (fs.length > +(inp.getAttribute('data-max') || 3)) msg = inp.getAttribute('data-msg-count');
      else if (fs.some(function (x) { return x.size > 8 * 1024 * 1024; })) msg = inp.getAttribute('data-msg-size');
      else if (fs.some(function (x) { return x.type && x.type.indexOf('image/') !== 0; })) msg = inp.getAttribute('data-msg-type');
      if (msg && er) er.textContent = msg;
      return !msg;
    },
    message: function (v) { return v.trim().length >= 10; },
    name: function (v) { return v.trim().length >= 3; },
    emp_no: function (v) { return /^\d{3,10}$/.test(digits(v)); },
    facility: function (v) { return v !== ''; },
    job_cat: function (v) { return v !== ''; },
    email: function (v) { return /^[a-z0-9][a-z0-9._%+\-]{0,63}@moh\.gov\.sa$/.test(v.trim().toLowerCase()); },
    mobile: function (v) { return /^05\d{8}$/.test(digits(v)); },
    consent: function () { return f.elements.consent.checked; }
  };
  var stepOf = { req_type: 1, topic: 1, message: 1, photos: 1, name: 2, emp_no: 2, facility: 2, job_cat: 2, email: 3, mobile: 3, consent: 3 };
  var focusId = { req_type: 'type-first' };
  function val(n) { var e = f.elements[n]; return e && e.value !== undefined ? e.value : ''; }
  function check(n, show) {
    var ok = (isAnon() && personal[n]) ? true : rules[n](val(n));
    var g = document.getElementById('g-' + n);
    if (g && show) {
      g.classList.toggle('bad', !ok);
      var el = document.getElementById(focusId[n] || n);
      if (el && el.setAttribute) { if (!ok) el.setAttribute('aria-invalid', 'true'); else el.removeAttribute('aria-invalid'); }
    }
    return ok;
  }
  Object.keys(rules).forEach(function (n) {
    [].forEach.call(f.querySelectorAll('[name=' + n + ']'), function (e) {
      // no validation on blur: an error appearing/disappearing between mousedown and mouseup would shift the
      // buttons and swallow the tap. Errors are shown on Next/Send and cleared as soon as the value is fixed.
      var clear = function () {
        var g = document.getElementById('g-' + n);
        if (g && g.classList.contains('bad') && rules[n](val(n))) check(n, true);
      };
      e.addEventListener('input', clear);
      e.addEventListener('change', clear);
    });
  });
  var m = f.elements.message, cnt = document.getElementById('cnt');
  function upd() { cnt.textContent = m.value.length; }
  m.addEventListener('input', upd); upd();

  var steps = [].slice.call(f.querySelectorAll('.fstep')), cur = 1, total = steps.length;
  var live = document.getElementById('live'), bar = document.getElementById('stepper');
  function show(n, focus) {
    cur = n;
    steps.forEach(function (s) { s.classList.toggle('on', +s.dataset.step === n); });
    if (bar) [].forEach.call(bar.children, function (li) {
      var k = +li.dataset.step; li.classList.toggle('on', k === n); li.classList.toggle('done', k < n);
      if (k === n) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
    });
    if (focus) {
      var lg = steps[n - 1].querySelector('legend');
      if (live && bar && bar.children[n - 1]) live.textContent = bar.children[n - 1].textContent;
      var first = [].filter.call(steps[n - 1].querySelectorAll('input:not([type=hidden]),select,textarea'),
        function (e) { return e.offsetParent !== null; })[0];
      window.scrollTo({ top: Math.max(0, f.getBoundingClientRect().top + window.pageYOffset - 150) });
      if (first) try { first.focus({ preventScroll: true }); } catch (e) { first.focus(); }
    }
  }
  function validateStep(n) {
    var first = null;
    Object.keys(rules).forEach(function (k) {
      if (stepOf[k] === n && !check(k, true) && !first) first = k;
    });
    if (first) {
      var el = document.getElementById(focusId[first] || first);
      var g = document.getElementById('g-' + first);
      if (g) g.scrollIntoView({ block: 'center' });
      if (el) try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
      if (live) { var er = document.getElementById('e-' + first); live.textContent = er ? er.textContent : ''; }
      return false;
    }
    return true;
  }
  document.documentElement.classList.contains('js') || document.documentElement.classList.add('js');
  [].forEach.call(f.querySelectorAll('.go'), function (b) {
    b.addEventListener('click', function () {
      var to = +b.dataset.go;
      if (to > cur) { for (var s = cur; s < to; s++) if (!validateStep(s)) return; }
      show(to, true);
    });
  });
  syncAnon();
  show(+f.dataset.start || 1, false);
  f.addEventListener('submit', function (ev) {
    // Enter key inside a step before the last one = "Next"
    if (cur < total) { ev.preventDefault(); if (validateStep(cur)) show(cur + 1, true); return; }
    var first = null;
    Object.keys(rules).forEach(function (n) { if (!check(n, true) && !first) first = n; });
    if (first) {
      ev.preventDefault();
      show(stepOf[first], false);
      var el = document.getElementById(focusId[first] || first);
      if (el) try { el.focus(); } catch (e) {}
      if (live) { var er = document.getElementById('e-' + first); live.textContent = er ? er.textContent : ''; }
      return;
    }
    if (isAnon()) {
      ['name', 'emp_no', 'email', 'mobile'].forEach(function (n) { f.elements[n].value = ''; });
      f.elements.job_cat.value = '';
      return;
    }
    if (anonChk) anonChk.checked = false;
    f.elements.email.value = f.elements.email.value.trim().toLowerCase();
    f.elements.mobile.value = digits(f.elements.mobile.value);
    f.elements.emp_no.value = digits(f.elements.emp_no.value);
  });
  var es = document.getElementById('errsum');
  if (es) es.focus();
})();
