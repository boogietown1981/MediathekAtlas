/* DMAX & TLC (0.6.48): the free on-demand programmes of the three Discovery channels in Germany
   (documentaries, reality, home and garden) with all episodes, in the shared platform panel
   (web/portal_panel.js). 0.6.50: every episode opens on the channel's website (own player not confirmed); discovery+-only or
   protected episodes open the channel's website. No offline copies. */
(() => {
  'use strict';
  window.MediathekAtlasDmax = window.AtlasPortalPanel?.({
    key: 'dmax', name: 'DMAX & TLC', short: 'DMAX & Co.', startView: 'series',
    play: () => window.playDmax, externalLink: 'Beim Sender ansehen',
    notPlayable: 'Diese Folge läuft vorerst nur auf der Website des Senders; bitte „Beim Sender ansehen“ wählen.'
  }) || undefined;
})();
