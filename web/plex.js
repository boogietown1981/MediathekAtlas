/* Plex (0.5.98): the free films, series and live channels of Plex ("Kostenlos auf Plex", no account)
   with the shared platform panel (web/portal_panel.js): categories, ratings, title and series pages.
   Some titles Plex delivers only with copy protection (Widevine): "Ansehen" checks the stream and
   such a title then only links to watch.plex.tv. Nothing is circumvented, no offline copies. */
(() => {
  'use strict';
  window.MediathekAtlasPlex = window.AtlasPortalPanel?.({
    key: 'plex', name: 'Plex', short: 'Plex', live: true,
    play: () => window.playPlex, externalLink: 'Bei Plex ansehen',
    notPlayable: 'Plex liefert diesen Titel nur mit Kopierschutz (Widevine) aus. MediathekAtlas umgeht ihn nicht; bitte bei Plex ansehen.'
  }) || undefined;
})();
