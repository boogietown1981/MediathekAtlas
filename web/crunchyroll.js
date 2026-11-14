/* Crunchyroll (0.5.96): anime series and films of crunchyroll.com with the shared platform panel
   (web/portal_panel.js): categories, ratings, title and series pages. Crunchyroll ended its free plan
   on 31.12.2025 and protects every stream with Widevine: every title opens crunchyroll.com
   ("Bei Crunchyroll ansehen", optional Chrome extension for the play click). Nothing is circumvented,
   no offline copies. Free Crunchyroll episodes come from the official YouTube channel (source YouTube). */
(() => {
  'use strict';
  window.MediathekAtlasCrunchyroll = window.AtlasPortalPanel?.({
    key: 'crunchyroll', name: 'Crunchyroll', short: 'Crunchyroll', startView: 'series',
    play: () => null, externalLink: 'Bei Crunchyroll ansehen',
    notPlayable: 'Crunchyroll liefert diesen Titel nur mit Kopierschutz (Widevine) und mit Abo aus. MediathekAtlas umgeht ihn nicht; bitte bei Crunchyroll ansehen.'
  }) || undefined;
  const pick = document.getElementById('crunchyroll-pick');
  if (pick) pick.onchange = () => window.MediathekAtlasCrunchyroll?.refresh?.();
})();
