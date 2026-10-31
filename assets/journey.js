(function () {
  'use strict';
  var emp = document.getElementById('s-emp'), svc = document.getElementById('s-svc');
  var reset = document.getElementById('s-reset'), cnt = document.getElementById('s-count');
  var wrap = document.getElementById('journey');
  if (!emp || !svc || !wrap) return;
  var items = [].slice.call(wrap.querySelectorAll('li.ji'));
  var stages = [].slice.call(wrap.querySelectorAll('section.stage'));
  function run() {
    var e = emp.value, s = svc.value, shown = 0;
    items.forEach(function (li) {
      var ok = (!e || li.dataset.emp === 'all' || li.dataset.emp === e) &&
               (!s || li.dataset.svc === 'all' || li.dataset.svc === s);
      li.hidden = !ok; if (ok) shown++;
    });
    stages.forEach(function (st) {
      var vis = st.querySelectorAll('li.ji:not([hidden])').length;
      var em = st.querySelector('.empty-st'); if (em) em.hidden = vis > 0;
    });
    cnt.textContent = (e || s) ? cnt.dataset.tpl.replace('{n}', shown) : '';
    try { sessionStorage.setItem('shq-j', e + '|' + s); } catch (x) {}
  }
  emp.addEventListener('change', run);
  svc.addEventListener('change', run);
  reset.addEventListener('click', function () { emp.value = ''; svc.value = ''; run(); });
  try {
    var p = (sessionStorage.getItem('shq-j') || '').split('|');
    if (p.length === 2) { emp.value = p[0]; svc.value = p[1]; if (emp.value !== p[0]) emp.value = ''; if (svc.value !== p[1]) svc.value = ''; }
  } catch (x) {}
  run();
})();
