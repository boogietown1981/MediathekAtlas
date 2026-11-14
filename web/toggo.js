/* TOGGO: films and children's series of toggo.de incl. TOGGOLINO, with the shared platform panel
   (web/portal_panel.js): categories, ratings, title and series pages. 0.5.87 follows TOGGO's real
   catalogue: every stream is copy protected (Widevine/PlayReady/FairPlay), so a title opens toggo.de.
   Nothing is circumvented, no offline copies. The player button appears only for a title TOGGO
   lists without copy protection. */
(() => {
  'use strict';
  window.MediathekAtlasToggo = window.AtlasPortalPanel?.({
    key: 'toggo', name: 'TOGGO', short: 'TOGGO', startView: 'series',
    play: () => window.playToggo, externalLink: 'Bei TOGGO ansehen',
    notPlayable: 'TOGGO liefert diesen Titel nur mit Kopierschutz aus. MediathekAtlas umgeht ihn nicht; bitte bei TOGGO ansehen.'
  }) || undefined;
  const pick = document.getElementById('toggo-pick');
  if (pick) pick.onchange = () => window.MediathekAtlasToggo?.refresh?.();
})();
