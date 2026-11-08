(function () {
  'use strict';
  var b = document.body, home = b.getAttribute('data-home') || '/kiosk', idle = +(b.getAttribute('data-idle') || 0);
  // return to the welcome screen after inactivity so the next employee never sees someone else's data
  if (idle > 0) {
    var tmr;
    var reset = function () { clearTimeout(tmr); tmr = setTimeout(function () { window.location.replace(home); }, idle * 1000); };
    ['pointerdown', 'keydown', 'input', 'touchstart', 'scroll'].forEach(function (ev) {
      document.addEventListener(ev, reset, { passive: true });
    });
    reset();
  }
  // request form: anonymous option only for complaints / suggestions / feedback
  var f = document.getElementById('kf');
  if (f) {
    var types = (f.getAttribute('data-anon-types') || '').split(','), box = document.getElementById('anonbox'), chk = f.elements.anonymous;
    var cur = function () { var r = f.querySelector('input[name=req_type]:checked') || f.querySelector('input[type=hidden][name=req_type]'); return r ? r.value : ''; };
    var sync = function () {
      var ok = types.indexOf(cur()) >= 0;
      if (box) box.classList.toggle('off', !ok);
      f.classList.toggle('anon', ok && chk && chk.checked);
    };
    [].forEach.call(f.querySelectorAll('input[name=req_type]'), function (r) { r.addEventListener('change', sync); });
    if (chk) chk.addEventListener('change', sync);
    sync();
    var es = document.getElementById('errsum'); if (es) es.focus();
  }
})();
