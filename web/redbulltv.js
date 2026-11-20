/* Red Bull TV (0.6.47): free sports and adventure documentaries, series, films and the Red Bull TV
   live channels, with the shared platform panel (web/portal_panel.js). Same Red Bull platform as
   ServusTV (servustv.py engine on the server); plain HLS without copy protection, played in the own
   player. 0.6.54: films and episodes can be kept as a private copy for 30 days (redbulltv_downloads.py). */
(() => {
  'use strict';
  window.MediathekAtlasRedBullTV = window.AtlasPortalPanel?.({
    key: 'redbulltv', name: 'Red Bull TV', short: 'Red Bull TV', live: true,
    play: () => window.playRedBullTV, externalLink: 'Bei Red Bull TV ansehen',
    notPlayable: 'Dieses Video gibt Red Bull TV nicht für fremde Player frei; bitte bei Red Bull TV ansehen.',
    offlineNote: days => `Red Bull TV bietet selbst keine Downloads an: private Kopie für ${days} Tage, nie länger als beim Sender verfügbar.`
  }) || undefined;
})();
