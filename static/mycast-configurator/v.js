/* T-743 (#452): one first-party visit count for a MyCast page. No cookie, no browser storage, no third party.
   Sends the page kind, the landing variant (?v=) and channel (?ch=) from the link, and only the referring site's
   host name, which the server turns into a category and drops. Skipped under Do Not Track or Global Privacy Control.
   ?synthetic=1 marks a test visit; the server stores it as synthetic and never counts it. */
(function () {
  try {
    if (navigator.globalPrivacyControl || navigator.doNotTrack === '1' || window.doNotTrack === '1') return;
    var me = document.currentScript;
    var page = (me && me.getAttribute('data-page')) || 'landing';
    var q = new URLSearchParams(location.search.slice(1) + '&' + location.hash.slice(1));
    var ref = '';
    try { ref = document.referrer ? new URL(document.referrer).hostname : ''; } catch (e) { ref = ''; }
    if (ref === location.hostname) ref = '';
    var body = JSON.stringify({ p: page, v: q.get('v') || '', ch: q.get('ch') || '', r: ref, s: q.get('synthetic') === '1' ? 1 : 0 });
    if (navigator.sendBeacon && navigator.sendBeacon('/api/mycast/v', body)) return;
    if (window.fetch) fetch('/api/mycast/v', { method: 'POST', body: body, keepalive: true, credentials: 'omit' }).catch(function () {});
  } catch (e) { /* counting must never break the page */ }
})();
