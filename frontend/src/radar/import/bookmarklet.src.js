/*
 * The "Send to Spyglass" bookmark button, in readable form. It runs on the page the reader is
 * looking at (never inside Spyglass) and hands that page to the reader's own Spyglass, which asks
 * before adding anything. bookmarklet.ts strips the comments and spaces, puts the address of the
 * running Spyglass in place of SPYGLASS_ORIGIN, puts this copy's secret in place of SPYGLASS_KEY
 * (Spyglass refuses pages that do not carry it) and turns the result into a javascript: link.
 *
 * Two ways to hand the page over, because sites differ:
 * 1. Open a small Spyglass window and send it the page with postMessage, addressed to the Spyglass
 *    origin only, every 250 ms until the window answers.
 * 2. When no answer came after 3 seconds (a site can cut the link between its windows), post the
 *    page to Spyglass as an ordinary form in that same window instead.
 *
 * Rules for this file: semicolons everywhere, no regular expressions, and no comment markers inside
 * strings, so the small minifier in bookmarklet.ts can read it. The built link must stay under
 * 2,000 characters.
 */
(function () {
  var origin = SPYGLASS_ORIGIN;
  var key = SPYGLASS_KEY;
  var doc = document;
  var limit = 6e6;
  var size = function (text) {
    return new Blob([text]).size;
  };
  var html = doc.documentElement.outerHTML;
  if (size(html) > limit) {
    var part = doc.querySelector('article') || doc.querySelector('main');
    html = part ? part.outerHTML : html;
  }
  if (size(html) > limit) {
    html = html.slice(0, 2e6);
  }
  var page = { type: 'spyglass:page', url: location.href, title: doc.title, html: html, key: key };
  var win = window.open(origin + '/#/import', 'spyglass_import', 'popup,width=640,height=760');
  if (!win) {
    alert('Your browser blocked the Spyglass window. Allow pop-ups for this site and try again.');
    return;
  }
  var done = false;
  var timer;
  var onAnswer = function (event) {
    if (event.origin === origin && event.data && event.data.type === 'spyglass:ack') {
      done = true;
      stop();
    }
  };
  var stop = function () {
    clearInterval(timer);
    removeEventListener('message', onAnswer);
  };
  addEventListener('message', onAnswer);
  timer = setInterval(function () {
    try {
      win.postMessage(page, origin);
    } catch (error) {
      stop();
    }
  }, 250);
  setTimeout(function () {
    if (done) {
      return;
    }
    stop();
    var form = doc.createElement('form');
    form.method = 'post';
    form.action = origin + '/api/radar/import/stage';
    form.enctype = 'multipart/form-data';
    form.acceptCharset = 'UTF-8';
    form.target = 'spyglass_import';
    form.style.display = 'none';
    ['url', 'title', 'html', 'key'].forEach(function (name) {
      var field = doc.createElement('input');
      field.type = 'hidden';
      field.name = name;
      field.value = page[name];
      form.appendChild(field);
    });
    (doc.body || doc.documentElement).appendChild(form);
    form.submit();
  }, 3000);
})();
