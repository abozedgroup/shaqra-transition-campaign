(function () {
  'use strict';
  var N = SHQ.norm;
  var q = document.getElementById('q'), list = document.getElementById('list');
  if (!q || !list) return;
  var items = [].slice.call(list.querySelectorAll('details.fq')).map(function (d) {
    var qt = d.querySelector('.qtext');
    return { el: d, qt: qt, orig: qt.textContent, text: N(d.textContent), cat: d.dataset.cat };
  });
  var cnt = document.getElementById('cnt'), empty = document.getElementById('empty');
  var cat = '';
  function hl(text, terms) {
    var out = SHQ.esc(text);
    terms.forEach(function (t) {
      if (t.length < 2) return;
      try { out = out.replace(new RegExp('(' + t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')(?![^<]*>)', 'gi'), '<mark>$1</mark>'); } catch (e) {}
    });
    return out;
  }
  function run() {
    var raw = q.value.trim(), terms = N(raw).split(' ').filter(Boolean), shown = 0;
    items.forEach(function (it) {
      var ok = (!cat || it.cat === cat) && terms.every(function (t) { return it.text.indexOf(t) > -1; });
      it.el.hidden = !ok;
      if (ok) { shown++; it.qt.innerHTML = terms.length ? hl(it.orig, raw.split(/\s+/)) : SHQ.esc(it.orig); if (terms.length && shown <= 3) it.el.open = true; else if (!terms.length) it.el.open = false; }
    });
    cnt.textContent = cnt.dataset.tpl.replace('{n}', shown);
    empty.classList.toggle('show', shown === 0);
    var ask = document.querySelectorAll('#ask-link,#ask-empty');
    [].forEach.call(ask, function (a) { a.href = a.dataset.base + (raw ? encodeURIComponent(raw.slice(0, 300)) : ''); });
  }
  q.addEventListener('input', run);
  document.querySelectorAll('#cats .chip').forEach(function (b) {
    b.addEventListener('click', function () {
      cat = b.dataset.cat; document.querySelectorAll('#cats .chip').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); }); run();
    });
  });
  var h = decodeURIComponent((location.hash.match(/^#q=(.*)$/) || [])[1] || '');
  if (h) { q.value = h; run(); }
  function openHash() {
    var m = location.hash.match(/^#(q[0-9A-Za-z-]+)$/);
    if (!m) return;
    var el = document.getElementById(m[1]);
    if (el && el.tagName === 'DETAILS') { el.hidden = false; el.open = true; el.scrollIntoView(); }
  }
  openHash();
  window.addEventListener('hashchange', openHash);
})();
