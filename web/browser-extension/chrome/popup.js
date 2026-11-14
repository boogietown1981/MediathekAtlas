'use strict';
const DEFAULTS = {autoplay: true, hdcp: true};
chrome.storage.sync.get(DEFAULTS, values => {
  for (const key of Object.keys(DEFAULTS)) {
    const box = document.getElementById(key);
    box.checked = !!values[key];
    box.onchange = () => chrome.storage.sync.set({[key]: box.checked}, () => {
      document.getElementById('state').textContent = 'Gespeichert. Gilt ab dem nächsten Link aus MediathekAtlas.';
    });
  }
});
