/* Rakuten TV (0.5.51): the free films, series and live channels of rakuten.tv with the shared
   platform panel (web/portal_panel.js): categories, ratings, details. Rakuten delivers free films
   and episodes only with copy protection (Widevine/PlayReady): they link to the official page,
   nothing is circumvented. Live channels (plain HLS) play in the MediathekAtlas player. */
(() => {
  'use strict';
  window.MediathekAtlasRakuten = window.AtlasPortalPanel?.({
    key: 'rakuten', name: 'Rakuten TV', short: 'Rakuten', live: true,
    play: () => window.playRakuten, externalLink: 'Bei Rakuten TV ansehen',
    notPlayable: 'Rakuten TV liefert kostenlose Filme und Folgen nur mit Kopierschutz (Widevine) aus. MediathekAtlas umgeht ihn nicht; bitte bei Rakuten TV ansehen.',
    offlineNote: days => `Rakuten TV: ${days} Tage Offline-Nutzung. Die Datei enthält die Werbung, die Rakuten ausliefert.`
  }) || undefined;
})();
