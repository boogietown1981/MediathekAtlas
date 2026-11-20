/* filmfriend (0.6.52): the film library of German public libraries as a catalogue with links, with the shared
   platform panel (web/portal_panel.js): categories, title pages, search, watchlist. Watching needs a library
   card login on filmfriend.de, so every title opens there ("Bei filmfriend ansehen"). No offline copies. */
(() => {
  'use strict';
  window.MediathekAtlasFilmfriend = window.AtlasPortalPanel?.({
    key: 'filmfriend', name: 'filmfriend', short: 'filmfriend',
    play: () => null, externalLink: 'Bei filmfriend ansehen',
    notPlayable: 'filmfriend-Filme laufen nur nach Anmeldung mit dem Ausweis einer teilnehmenden Bibliothek auf filmfriend.de.'
  }) || undefined;
})();
