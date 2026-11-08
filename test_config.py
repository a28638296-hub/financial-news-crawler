import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from digest_config import load_config


class ConfigTests(unittest.TestCase):
    def read(self, changes=None):
        config={'feeds':[{'id':'example','name':'Example','kind':'媒体报道','url':'https://example.com/feed'}]}
        config.update(changes or {})
        with TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            path.write_text(json.dumps(config),encoding='utf-8-sig')
            return load_config(path)

    def test_minimal_config_and_windows_bom(self):
        self.assertEqual(self.read()['max_workers'],3)
        self.assertEqual(self.read()['watchlist'],[])

    def test_path_like_source_id_and_duplicate_are_rejected(self):
        base=self.read()['feeds'][0]
        for sources in ([{**base,'id':'../outside'}],[base,base]):
            with self.subTest(sources=sources),self.assertRaises(ValueError):
                self.read({'feeds':sources})

    def test_credentials_and_invalid_urls_are_rejected(self):
        base=self.read()['feeds'][0]
        for url in ('https://reader:password@example.com/feed','file:///private','http://[',None):
            with self.subTest(url=url),self.assertRaises(ValueError):
                self.read({'feeds':[{**base,'url':url}]})

    def test_concurrency_timeout_and_page_bounds(self):
        for changes in ({'max_workers':0},{'max_workers':9},{'request_timeout':False},{'request_timeout':31},
                        {'financial_news_hours':72},{'mode':'stocks'},{'feeds':[]}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.read(changes)
        base=self.read()['feeds'][0]
        with self.assertRaises(ValueError):self.read({'feeds':[{**base,'max_pages':100}]})


if __name__=='__main__':
    unittest.main()
