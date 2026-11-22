"""0.6.87: Bewertung der Erkennung (Air, 0.6.85, 22.11.2026): das ZDF-Thema „Doku“ wurde direkt über die IMDb-Suche
als Serie „Doku“ erkannt (93 Werke). 0.6.86 sperrte nur die Vorlage; die Suche nach dem Thema als Serie blieb."""
import unittest
from unittest.mock import patch

import catalog
import metadata
import negative_cache
import imdb_archive


class SubjectTopics(unittest.TestCase):
    def queried(self, topic, title='Die Macht der Algorithmen', description='Eine Dokumentation.'):
        row = {'title': title, 'topic': topic, 'duration': 2600, 'channel': 'ZDF', 'description': description}
        meta = catalog.seed(row)
        seen = []
        def tvdb(row, meta, credential, kind, title):
            seen.append((kind, title));return []
        with patch.object(metadata, 'tvdb_candidates', side_effect=tvdb), \
             patch.object(negative_cache, 'contains', return_value=False), \
             patch.object(imdb_archive, 'ACTIVE', None):
            metadata.candidates(row, meta, {'tvdb': 'k', 'tvdb_pin': ''})
        return meta, seen

    def test_subject_topics_are_not_searched_as_series(self):
        for topic in ('Doku', 'Sport', 'Masterclass', 'Kultur'):
            meta, seen = self.queried(topic, description='Serie über ' + topic)
            self.assertNotEqual(catalog.key(meta['title']), catalog.key(topic), topic)
            self.assertNotIn(('series', topic), [(k, t) for k, t in seen], topic)
        _, seen = self.queried('Terra X')
        self.assertIn('Terra X', [t for _, t in seen])

    def test_subject_series_never_chosen_for_its_own_topic(self):
        imdb_doku = {'kind': 'series', 'title': 'Doku', 'provider': 'IMDb Offline', 'reference_id': 'tt9'}
        self.assertTrue(catalog.portal_identity(imdb_doku, 'Doku'))
        self.assertFalse(catalog.portal_identity(imdb_doku, 'Terra X'))
        self.assertFalse(catalog.portal_identity({'kind': 'series', 'title': 'Puls'}, 'Puls'))
        self.assertFalse(catalog.template_topic('Doku'))


if __name__ == '__main__':
    unittest.main()
