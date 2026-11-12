/* Pluto TV (0.5.36): public catalogue (films, series, live channels), playback in the in-app player.
   0.5.37/0.5.38: 30 days offline, categories, ratings and details. Since 0.5.40 the panel itself is the
   shared web/portal_panel.js (also used by JustWatch TV); this file only configures it. */
(() => {
  'use strict';
  window.MediathekAtlasPluto = window.AtlasPortalPanel?.({
    key: 'pluto', name: 'Pluto TV', short: 'Pluto', live: true,
    play: () => window.playPluto,
    offlineNote: days => `Pluto TV erlaubt ${days} Tage Offline-Nutzung. Die Datei enthält die Werbung, die Pluto ausliefert.`
  }) || undefined;
})();
