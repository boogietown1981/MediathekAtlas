/* dailyme TV (0.6.62): free films, series, anime and documentaries with adverts, as a catalogue with links in the
   shared platform panel (web/portal_panel.js): categories, title pages, episodes, search, watchlist. dailyme plays
   only in its own player (session and access key per video), so every title opens on dailyme.de
   ("Bei dailyme ansehen"). No offline copies here; the offline mode is part of the dailyme app. */
(() => {
  'use strict';
  window.MediathekAtlasDailyme = window.AtlasPortalPanel?.({
    key: 'dailyme', name: 'dailyme TV', short: 'dailyme',
    play: () => null, externalLink: 'Bei dailyme ansehen',
    notPlayable: 'dailyme TV spielt seine Videos nur im eigenen Player; bitte „Bei dailyme ansehen“ wählen. Offline geht nur in der dailyme-App.'
  }) || undefined;
})();
