/* JustWatch TV (0.5.40): JustWatch's own free films and series (package "jwt") with the shared
   platform panel (web/portal_panel.js): categories, ratings, details, playback for titles with
   an external-player stream, 30 days offline. Other titles link to the official JustWatch page. */
(() => {
  'use strict';
  window.MediathekAtlasJustWatch = window.AtlasPortalPanel?.({
    key: 'justwatch', name: 'JustWatch TV', short: 'JustWatch', live: false,
    play: () => window.playJustWatch, externalLink: 'Bei JustWatch ansehen',
    nightOffline: true,
    notPlayable: 'JustWatch gibt diesen Titel gerade nicht frei (oft Jugendschutz: nur 0 bis 6 Uhr). Der Download lässt sich für heute Nacht vormerken.',
    offlineNote: days => `JustWatch TV erlaubt ${days} Tage Offline-Nutzung. Die Datei enthält die Werbung, die JustWatch ausliefert.`
  }) || undefined;
})();
