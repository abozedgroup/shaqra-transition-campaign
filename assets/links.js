(function () {
  'use strict';
  var N = SHQ.norm;
  var q = document.getElementById('q'), list = document.getElementById('list');
  if (!q || !list) return;
  var cats = [].slice.call(list.querySelectorAll('details.lcat'));
  var rows = [].slice.call(list.querySelectorAll('.lrow')).map(function (r) { return { el: r, text: N(r.textContent), aud: r.dataset.aud, org: r.dataset.org, en: r.dataset.en }; });
  var cnt = document.getElementById('cnt'), empty = document.getElementById('empty'), nsnote = document.getElementById('nsnote');
  var org = document.getElementById('org'), enOnly = document.getElementById('en-only');
  var aud = 'all', openState = null;
  function run() {
    var terms = N(q.value).split(' ').filter(Boolean), shown = 0;
    var filtered = terms.length > 0 || aud !== 'all' || org.value || enOnly.checked;
    rows.forEach(function (r) {
      var ok = terms.every(function (t) { return r.text.indexOf(t) > -1; });
      if (aud === 'nonsaudi' && r.aud === 'saudi') ok = false;
      if (org.value && r.org !== org.value) ok = false;
      if (enOnly.checked && r.en !== '1') ok = false;
      r.el.hidden = !ok; if (ok) shown++;
    });
    cats.forEach(function (c) {
      var vis = c.querySelectorAll('.lrow:not([hidden])').length;
      c.hidden = vis === 0;
      var n = c.querySelector('.cat-count'); if (n) n.textContent = vis;
      if (filtered && vis) c.open = true; else if (!filtered) c.open = false;
    });
    cnt.textContent = cnt.dataset.tpl.replace('{n}', shown);
    empty.classList.toggle('show', shown === 0);
    if (nsnote) nsnote.hidden = aud !== 'nonsaudi';
  }
  q.addEventListener('input', run);
  org.addEventListener('change', run);
  enOnly.addEventListener('change', run);
  document.querySelectorAll('[data-aud].chip').forEach(function (b) {
    b.addEventListener('click', function () {
      aud = b.dataset.aud; document.querySelectorAll('[data-aud].chip').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); }); run();
    });
  });
  document.getElementById('reset').addEventListener('click', function () {
    q.value = ''; org.value = ''; enOnly.checked = false; aud = 'all';
    document.querySelectorAll('[data-aud].chip').forEach(function (x) { x.setAttribute('aria-pressed', x.dataset.aud === 'all' ? 'true' : 'false'); }); run();
  });
  document.getElementById('expand').addEventListener('click', function () { cats.forEach(function (c) { if (!c.hidden) c.open = true; }); });
  document.getElementById('collapse').addEventListener('click', function () { cats.forEach(function (c) { c.open = false; }); });
})();
