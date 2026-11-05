import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bibleit import translation


class LocalImportTests(unittest.TestCase):
    def test_import_and_read_without_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.write_text(''.join(f'Book {i} 1:1 Text {i}\n' for i in range(1, 67)))
            with patch.object(translation, 'TRANSLATIONS_DIR', root), patch.object(
                translation, 'get_languages_config', side_effect=AssertionError('network used')
            ):
                translation.import_local(source, 'LOCAL', 'Local Bible')
                self.assertEqual(translation.get_installed()['LOCAL'].name, 'Local Bible')
                with translation.open('LOCAL') as bible:
                    self.assertIn('Text 40', list(bible.read(translation.TranslationRef(40, 1, 1)))[0].decode())
                with self.assertRaises(ValueError):
                    translation.import_local(source, 'LOCAL')
                translation.uninstall('LOCAL')
                self.assertFalse((root / 'LOCAL.local.json').exists())

    def test_rejects_incomplete_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.write_text('Genesis 1:1 Text\n')
            with patch.object(translation, 'TRANSLATIONS_DIR', root):
                with self.assertRaisesRegex(ValueError, '66 books'):
                    translation.import_local(source, 'LOCAL')
                self.assertFalse((root / 'LOCAL.bt').exists())
