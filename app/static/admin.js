(function () {
  'use strict';
  var d = document.querySelector('.delform');
  if (d) d.addEventListener('submit', function (e) { if (!window.confirm(d.getAttribute('data-confirm'))) e.preventDefault(); });
})();
