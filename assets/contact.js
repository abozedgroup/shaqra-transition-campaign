(function () {
  'use strict';
  var b = document.getElementById('copy'), m = document.getElementById('copied');
  if (!b) return;
  b.addEventListener('click', function () {
    var done = function () { m.style.display = 'inline'; setTimeout(function () { m.style.display = 'none'; }, 2500); };
    if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.mail).then(done, function () {});
  });
})();
