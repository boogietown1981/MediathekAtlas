/* RTL+ (0.5.102): the free titles of RTL+ ("RTL+ Free") as a catalogue with links, with the shared
   platform panel (web/portal_panel.js): categories, title pages, search, watchlist. Every RTL+ stream
   uses Widevine: each title opens plus.rtl.de ("Bei RTL+ ansehen", optional Chrome extension for the
   play click). Nothing is circumvented, no offline copies. */
(() => {
  'use strict';
  window.MediathekAtlasRtlPlus = window.AtlasPortalPanel?.({
    key: 'rtlplus', name: 'RTL+', short: 'RTL+',
    play: () => null, externalLink: 'Bei RTL+ ansehen',
    notPlayable: 'RTL+ liefert alle Videos nur mit Kopierschutz (Widevine) aus. MediathekAtlas umgeht ihn nicht; bitte bei RTL+ ansehen.'
  }) || undefined;
})();
