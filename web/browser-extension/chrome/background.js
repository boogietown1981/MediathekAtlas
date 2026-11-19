/* MediathekAtlas Videostart, seit 0.6.38: Hintergrund (Service Worker).
 *
 * - „reload“ von der MediathekAtlas-Seite: Erweiterung aus ihrem Ordner neu laden. MediathekAtlas schreibt
 *   den Ordner bei jedem Start mit der aktuellen Fassung neu; so kommt ein Update ohne Handarbeit an.
 * - Nach Installation oder Update: Verbindungsskript in bereits offene MediathekAtlas-Tabs einsetzen, damit
 *   der Einrichtungsassistent die Erweiterung sofort erkennt (ohne die Seite neu zu laden).
 */
'use strict';
const ATLAS_TABS = ['http://127.0.0.1/*', 'http://localhost/*'];

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
