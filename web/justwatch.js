/* JustWatch TV (0.5.40): JustWatch's own free films and series (package "jwt") with the shared
   platform panel (web/portal_panel.js): categories, ratings, details, playback for titles with
   an external-player stream, 30 days offline. Other titles link to the official JustWatch page. */
(() => {
  'use strict';
  window.MediathekAtlasJustWatch = window.AtlasPortalPanel?.({
    key: 'justwatch', name: 'JustWatch TV', dialogPrefix: 'atlas-jw', dialogId: 'atlas-justwatch-detail', short: 'JustWatch', live: false,
    play: () => window.playJustWatch, externalLink: 'Bei JustWatch ansehen',
    notPlayable: 'JustWatch gibt diesen Titel nicht für externe Player frei; Ansehen und Speichern nur auf der JustWatch-Seite.',
    offlineNote: days => `JustWatch TV erlaubt ${days} Tage Offline-Nutzung. Die Datei enthält die Werbung, die JustWatch ausliefert.`
  }) || undefined;
})();
