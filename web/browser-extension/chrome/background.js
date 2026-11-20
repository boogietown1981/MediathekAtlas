/* MediathekAtlas Videostart, seit 0.6.38: Hintergrund (Service Worker).
 *
 * - „reload“ von der MediathekAtlas-Seite: Erweiterung aus ihrem Ordner neu laden. MediathekAtlas schreibt
 *   den Ordner bei jedem Start mit der aktuellen Fassung neu; so kommt ein Update ohne Handarbeit an.
 * - Nach Installation oder Update: Verbindungsskript in bereits offene MediathekAtlas-Tabs einsetzen, damit
 *   der Einrichtungsassistent die Erweiterung sofort erkennt (ohne die Seite neu zu laden).
 */
'use strict';
const ATLAS_TABS = ['http://127.0.0.1/*', 'http://localhost/*'];

// 0.6.46: Fenster des Anbieter-Tabs auf Vollbild stellen, sobald das Video läuft (autostart.js), und den
// vorherigen Zustand wiederherstellen, wenn der Nutzer mit Esc beendet oder den Tab schließt.
// chrome.windows braucht dafür keine zusätzliche Berechtigung und keine Eingabe des Nutzers.
const store = chrome.storage.session || chrome.storage.local;
const KEY = 'fullscreenTabs';
const saved = () => new Promise(resolve => store.get({[KEY]: {}}, v => resolve((v && v[KEY]) || {})));
const save = map => new Promise(resolve => store.set({[KEY]: map}, resolve));
async function enterFullscreen(tab) {
  const map = await saved();
  chrome.windows.get(tab.windowId, win => {
    if (chrome.runtime.lastError || !win) return;
    if (win.state !== 'fullscreen') {
      map[tab.id] = {windowId: win.id, state: win.state || 'normal'};
      save(map);
      chrome.windows.update(win.id, {state: 'fullscreen'}, () => void chrome.runtime.lastError);
    }
  });
}
async function leaveFullscreen(tabId) {
  const map = await saved();
  const entry = map[tabId];
  if (!entry) return;
  delete map[tabId];
  await save(map);
  if (Object.values(map).some(e => e.windowId === entry.windowId)) return;   // ein anderes Video in diesem Fenster läuft noch
  chrome.windows.get(entry.windowId, win => {
    if (chrome.runtime.lastError || !win || win.state !== 'fullscreen') return;
    chrome.windows.update(win.id, {state: ['normal', 'maximized'].includes(entry.state) ? entry.state : 'normal'}, () => void chrome.runtime.lastError);
  });
}
chrome.runtime.onMessage.addListener((message, sender) => {
  if (!message || !sender.tab) return;
  if (message.type === 'fullscreen') enterFullscreen(sender.tab);
  else if (message.type === 'fullscreen-exit') leaveFullscreen(sender.tab.id);
});
chrome.tabs.onRemoved.addListener(tabId => { leaveFullscreen(tabId); });

chrome.runtime.onMessage.addListener((message, sender) => {
  if (!message || message.type !== 'reload' || !sender.tab || !sender.url) return;
  let host = '';
  try { host = new URL(sender.url).hostname; } catch (e) { return; }
  if (host !== '127.0.0.1' && host !== 'localhost') return;
  chrome.runtime.reload();
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.tabs.query({url: ATLAS_TABS}, tabs => {
    for (const tab of tabs || []) {
      chrome.scripting.executeScript({target: {tabId: tab.id}, files: ['atlas_bridge.js']}).catch(() => {});
    }
  });
});
