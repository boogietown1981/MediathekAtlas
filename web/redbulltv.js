/* Red Bull TV (0.6.47): free sports and adventure documentaries, series, films and the Red Bull TV
   live channels, with the shared platform panel (web/portal_panel.js). Same Red Bull platform as
   ServusTV (servustv.py engine on the server); plain HLS without copy protection, played in the own
   player. No offline copies. */
(() => {
  'use strict';
  window.MediathekAtlasRedBullTV = window.AtlasPortalPanel?.({
    key: 'redbulltv', name: 'Red Bull TV', short: 'Red Bull TV', live: true,
    play: () => window.playRedBullTV, externalLink: 'Bei Red Bull TV ansehen',
    notPlayable: 'Dieses Video gibt Red Bull TV nicht für fremde Player frei; bitte bei Red Bull TV ansehen.'
  }) || undefined;
})();
