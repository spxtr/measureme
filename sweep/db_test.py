import io
import gzip
import json
import os.path
import tempfile
import unittest

import sweep.db as db


def _count_lines(path: str):
    lines = 0
    with open(path, 'rt') as f:
        for _ in f:
            lines += 1
    return lines


class TestReaderWriter(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def test_write_then_read(self):
        with db.Writer(self.dir.name) as w:
            w.add_point([0])
            w.add_point([1, 'foo'])
            w.metadata['foo'] = 'bar'
            w.add_blob('foo.dat', b'bar')

        with db.Reader(self.dir.name, w.id) as r:
            for i, line in enumerate(r):
                self.assertLessEqual(i, 1)
            self.assertEqual(i, 1)

            # Twice to make sure it rewinds.
            self.assertEqual(len(r.all_data()), 2)
            self.assertEqual(len(r.all_data()), 2)

            self.assertEqual(r.all_data()[0][0], '0')
            self.assertEqual(r.all_data()[1][0], '1')
            self.assertEqual(r.all_data()[1][1], 'foo')

            self.assertEqual(r.metadata['foo'], 'bar')
            self.assertEqual(r.blob('foo.dat'), b'bar')

            for i, line in enumerate(r):
                self.assertLessEqual(i, 1)
            self.assertEqual(i, 1)

    def test_add_point(self):
        with db.Writer(self.dir.name) as w:
            w.add_point([0])
        self.assertEqual(w.id, 0)

        with db.Writer(self.dir.name) as w:
            w.add_point([1, None])
        self.assertEqual(w.id, 1)

        # Hit the max id.
        with self.assertRaises(RuntimeError):
            db.Writer(self.dir.name, max_id=1)

        self.assertTrue(os.path.isdir(os.path.join(self.dir.name, '0')))
        self.assertTrue(os.path.isdir(os.path.join(self.dir.name, '1')))

        with gzip.open(os.path.join(self.dir.name, '0', 'data.tsv.gz')) as f:
            self.assertEqual(f.read(), b'0\r\n')

        with gzip.open(os.path.join(self.dir.name, '1', 'data.tsv.gz')) as f:
            self.assertEqual(f.read(), b'1\t\r\n')

    def test_metadata(self):
        with db.Writer(self.dir.name) as w:
            w.metadata['foo'] = 'bar'

        with open(w.metadatapath) as f:
            dat = json.load(f)
        self.assertIn('foo', dat)
        self.assertEqual(dat['foo'], 'bar')

    def test_add_blob(self):
        with db.Writer(self.dir.name) as w:
            w.add_blob('foo.txt', b'bar')
        with open(os.path.join(w.dir, 'foo.txt'), 'rb') as f:
            self.assertEqual(f.read(), b'bar')


if __name__ == '__main__':
    unittest.main()
