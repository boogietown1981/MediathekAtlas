/* ServusTV On (0.5.101): the free video library of ServusTV (formats with all episodes, films,
   documentaries) and the ServusTV live channels, with the shared platform panel
   (web/portal_panel.js). Plain HLS without copy protection, played in the own player; youth
   protection hours and geo blocks are named by the server. No offline copies. */
(() => {
  'use strict';
  window.MediathekAtlasServusTV = window.AtlasPortalPanel?.({
    key: 'servustv', name: 'ServusTV', short: 'ServusTV', live: true,
    play: () => window.playServusTV, externalLink: 'Bei ServusTV ansehen',
    notPlayable: 'Dieses Video gibt ServusTV nicht für fremde Player frei; bitte bei ServusTV ansehen.'
  }) || undefined;
})();
