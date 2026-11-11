'use strict';
// Read-only, local metadata-audit overview. Uses existing authenticated API helper.
(function () {
  const box = document.getElementById('video-audit-panel');
  if (!box) return;
  const progress = document.getElementById('video-audit-progress');
  const bar = document.getElementById('video-audit-bar');
  const results = document.getElementById('video-audit-results');
  let busy = false;
  const de = new Intl.NumberFormat('de-DE');
  async function refreshVideoAudit() {
    if (busy || document.getElementById('review').hidden) return;
    busy = true;
    try {
      const res = await api('video-audit');
      const total = Number(res.total_at_start || 0), done = Number(res.processed || 0);
      const percent = total ? Math.min(100, Math.round(100 * done / total)) : 0;
      bar.max = 100;
      bar.value = res.phase === 'complete' ? 100 : percent;
      progress.textContent = `${res.phase === 'complete' ? 'Abgeschlossen' : 'Läuft'} · ${de.format(done)} von ${de.format(total)} Bestandswerken (${res.phase === 'complete' ? 100 : percent} %) · ${de.format(res.checked)} genauer geprüft · ${de.format(res.flagged)} Auffälligkeiten · ${de.format(res.manual_flags)} davon manuelle Zuordnungen unverändert`;
      results.replaceChildren();
      for (const row of res.findings || []) {
        const entry = document.createElement('article'); entry.className = 'atlas-audit-entry';
        const title = document.createElement('strong'); title.textContent = row.title || 'Werk nicht mehr vorhanden';
        const note = document.createElement('small'); note.textContent = `${row.previous_state === 'manual' ? 'Manuell bestätigt – nicht verändert' : row.previous_state === 'matched' ? 'Auto-bestätigt – markiert' : 'Werk erkannt – markiert'} · ${row.video_role}`;
        const reason = document.createElement('small'); reason.textContent = row.reason || '';
        entry.append(title, note, reason); results.append(entry);
      }
    } catch (err) {
      progress.textContent = 'Prüfstand nicht verfügbar: ' + (err.message || 'Unbekannter Fehler');
    } finally { busy = false; }
  }
  document.getElementById('video-audit-refresh').addEventListener('click', refreshVideoAudit);
  document.querySelector('[data-view="review"]').addEventListener('click', refreshVideoAudit);
  setInterval(() => { if (!document.hidden && !document.getElementById('review').hidden) refreshVideoAudit(); }, 16000);
})();
