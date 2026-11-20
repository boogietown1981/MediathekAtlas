/* DMAX, TLC & HGTV (0.6.48): the free on-demand programmes of the three Discovery channels in Germany
   (documentaries, reality, home and garden) with all episodes, in the shared platform panel
   (web/portal_panel.js). Episodes without copy protection play in the own player; discovery+-only or
   protected episodes open the channel's website. No offline copies. */
(() => {
  'use strict';
  window.MediathekAtlasDmax = window.AtlasPortalPanel?.({
    key: 'dmax', name: 'DMAX, TLC & HGTV', short: 'DMAX & Co.', startView: 'series',
    play: () => window.playDmax, externalLink: 'Beim Sender ansehen',
    notPlayable: 'Diese Folge gibt der Sender nur in seiner eigenen Seite oder mit discovery+ frei; bitte beim Sender ansehen.'
  }) || undefined;
})();
