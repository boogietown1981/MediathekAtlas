/* Joyn (0.5.65): films, series and live channels of joyn.de with the shared platform panel
   (web/portal_panel.js): categories, ratings, details. Free titles and Joyn+ titles are both listed,
   Joyn+ is a category of its own. Joyn plays only in its own player (Widevine as far as known):
   every title and channel opens joyn.de, nothing is circumvented and no Joyn login is stored. */
(() => {
  'use strict';
  window.MediathekAtlasJoyn = window.AtlasPortalPanel?.({
    key: 'joyn', name: 'Joyn', short: 'Joyn', live: true,
    play: () => null, externalLink: 'Bei Joyn ansehen',
    notPlayable: 'Joyn spielt Titel nur im eigenen Player ab (in der Regel mit Kopierschutz). MediathekAtlas umgeht ihn nicht; bitte bei Joyn ansehen.'
  }) || undefined;
})();
