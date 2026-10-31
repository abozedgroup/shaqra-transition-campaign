(function () {
  'use strict';
  var f = document.getElementById('f');
  if (!f) return;
  var AR = '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹';
  function digits(s) {
    return s.replace(/[٠-٩۰-۹]/g, function (c) { return String(AR.indexOf(c) % 10); }).replace(/\s+/g, '');
  }
  var rules = {
    req_type: function () { return !!f.querySelector('input[name=req_type]:checked'); },
    name: function (v) { return v.trim().length >= 3; },
    emp_no: function (v) { return /^\d{3,10}$/.test(digits(v)); },
    email: function (v) { return /^[a-z0-9][a-z0-9._%+\-]{0,63}@moh\.gov\.sa$/.test(v.trim().toLowerCase()); },
    mobile: function (v) { return /^05\d{8}$/.test(digits(v)); },
    facility: function (v) { return v !== ''; },
    job_cat: function (v) { return v !== ''; },
    message: function (v) { return v.trim().length >= 10; },
    consent: function () { return f.elements.consent.checked; }
  };
  function val(n) { var e = f.elements[n]; return e && e.value !== undefined ? e.value : ''; }
  function check(n, show) {
    var ok = rules[n](val(n));
    var g = document.getElementById('g-' + n);
    if (g && show) g.classList.toggle('bad', !ok);
    return ok;
  }
  Object.keys(rules).forEach(function (n) {
    var els = f.querySelectorAll('[name=' + n + ']');
    Array.prototype.forEach.call(els, function (e) {
      e.addEventListener('blur', function () { check(n, true); });
      e.addEventListener('change', function () { check(n, true); });
    });
  });
  var m = f.elements.message, cnt = document.getElementById('cnt');
  function upd() { cnt.textContent = m.value.length; }
  m.addEventListener('input', upd); upd();
  f.addEventListener('submit', function (ev) {
    var first = null;
    Object.keys(rules).forEach(function (n) {
      if (!check(n, true) && !first) first = n;
    });
    if (first) {
      ev.preventDefault();
      var g = document.getElementById('g-' + first);
      if (g) g.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    f.elements.email.value = f.elements.email.value.trim().toLowerCase();
    f.elements.mobile.value = digits(f.elements.mobile.value);
    f.elements.emp_no.value = digits(f.elements.emp_no.value);
  });
})();
