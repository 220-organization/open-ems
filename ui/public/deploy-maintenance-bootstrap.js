(function () {
  var POLL_MS = 3000;

  function resolveLang() {
    try {
      var params = new URLSearchParams(window.location.search);
      var fromUrl = params.get('lang') || params.get('locale');
      if (fromUrl) return fromUrl.trim().toLowerCase().split('-')[0];
    } catch (e) {
      /* ignore */
    }
    try {
      var stored = localStorage.getItem('pf-lang');
      if (stored) return stored.trim().toLowerCase().split('-')[0];
    } catch (e) {
      /* ignore */
    }
    return 'uk';
  }

  function message() {
    var lang = resolveLang();
    var bag = window.DEPLOY_MAINTENANCE_I18N || {};
    return bag[lang] || bag.en || bag.uk || 'All is ok, we are upgrading, will be available in ~ 2 mins';
  }

  function shell() {
    return document.getElementById('deploy-maintenance-bootstrap');
  }

  function show() {
    if (window.__OPEN_EMS_APP_MOUNTED) return;
    var el = shell();
    if (!el) return;
    var msg = el.querySelector('.deploy-maintenance-bootstrap__text');
    if (msg) msg.textContent = message();
    el.hidden = false;
  }

  function hide() {
    var el = shell();
    if (el) el.hidden = true;
  }

  function check() {
    if (window.__OPEN_EMS_APP_MOUNTED) return;
    fetch('/api/health', { cache: 'no-store' })
      .then(function (r) {
        if (r.ok) hide();
        else show();
      })
      .catch(show);
  }

  check();
  window.setInterval(check, POLL_MS);
})();
