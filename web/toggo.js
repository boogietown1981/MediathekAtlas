/* TOGGO (0.5.79): the children's series of toggo.de incl. TOGGOLINO, with the shared platform panel
   (web/portal_panel.js): categories, ratings, series pages. Series only (no single films, no live
   channels). An episode plays in the MediathekAtlas player only if TOGGO lists a stream without copy
   protection; otherwise it opens toggo.de. Nothing is circumvented, no offline copies. */
(() => {
  'use strict';
  window.MediathekAtlasToggo = window.AtlasPortalPanel?.({
    key: 'toggo', name: 'TOGGO', short: 'TOGGO', startView: 'series', seriesOnly: true,
    play: () => window.playToggo, externalLink: 'Bei TOGGO ansehen',
    notPlayable: 'TOGGO liefert diese Folge nur mit Kopierschutz aus. MediathekAtlas umgeht ihn nicht; bitte bei TOGGO ansehen.'
  }) || undefined;
})();
