(function () {
  var script = document.currentScript;

  // Copier le contenu d'un bloc de code
  document.querySelectorAll('.code-block').forEach(function (block) {
    var btn = block.querySelector('.copy');
    var code = block.querySelector('pre code') || block.querySelector('pre');
    if (!btn || !code) return;
    btn.addEventListener('click', function () {
      var text = code.innerText.replace(/\n$/, '');
      var done = function () {
        btn.textContent = 'Copié';
        btn.classList.add('done');
        setTimeout(function () { btn.textContent = 'Copier'; btn.classList.remove('done'); }, 1500);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done);
      } else {
        var ta = document.createElement('textarea');
        ta.value = text; document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); done(); } catch (e) {}
        document.body.removeChild(ta);
      }
    });
  });

  // Menu sur petit écran
  var toggle = document.querySelector('.entete .menu-btn');
  if (toggle) {
    toggle.addEventListener('click', function () { document.body.classList.toggle('nav-open'); });
    document.querySelectorAll('.sidebar a').forEach(function (a) {
      a.addEventListener('click', function () { document.body.classList.remove('nav-open'); });
    });
  }

  // Garder l'entrée active visible dans le menu
  var active = document.querySelector('.sidebar .nav-item.active');
  var sidebar = document.querySelector('.sidebar');
  if (active && sidebar) {
    var top = active.offsetTop - sidebar.clientHeight / 3;
    if (top > 0) sidebar.scrollTop = top;
  }

  // Ouvrir les corrections à l'impression
  window.addEventListener('beforeprint', function () {
    document.querySelectorAll('details').forEach(function (d) { d.setAttribute('data-was-open', d.open ? '1' : '0'); d.open = true; });
  });
  window.addEventListener('afterprint', function () {
    document.querySelectorAll('details').forEach(function (d) { if (d.getAttribute('data-was-open') === '0') d.open = false; });
  });

  // Supports mis en ligne au fil des séances : griser les liens vers les documents pas encore ouverts
  var cibles = document.querySelectorAll('[data-doc]');
  if (!cibles.length || !script || !script.src || location.protocol === 'file:' || !window.fetch) return;
  var url = script.src.replace(/app\.js(\?.*)?$/, 'publie.json');

  function verrouiller(el) {
    var info = 'Pas encore disponible';
    if (el.tagName === 'TR') {
      el.classList.add('a-venir');
      var acces = el.querySelector('td.acces');
      if (acces) acces.innerHTML = '<span class="etat">À venir</span>';
      return;
    }
    if (el.tagName === 'A') {
      var sp = document.createElement('span');
      sp.className = (el.className ? el.className + ' ' : '') + 'verrou-lien';
      sp.innerHTML = el.innerHTML;
      sp.title = info;
      if (el.parentNode) el.parentNode.replaceChild(sp, el);
      return;
    }
    el.classList.add('verrou');
    el.title = info;
  }

  fetch(url, { cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d || !d.documents || !d.documents.forEach) return;
      var ok = {};
      d.documents.forEach(function (f) { ok[f] = true; });
      // les lignes du tableau d'abord, puis les liens restants
      var liste = Array.prototype.slice.call(document.querySelectorAll('[data-doc]'));
      liste.sort(function (a, b) { return (a.tagName === 'TR' ? 0 : 1) - (b.tagName === 'TR' ? 0 : 1); });
      liste.forEach(function (el) {
        if (!ok[el.getAttribute('data-doc')] && el.isConnected) verrouiller(el);
      });
    })
    .catch(function () {});
})();
