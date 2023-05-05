import csv
import gzip
import hashlib
import json
import shutil
import os
import os.path
from typing import Dict, List


def _files_equal(uncompressed: str, compressed: str) -> bool:
    BUF_SIZE = 65536
    md51 = hashlib.md5()
    with open(uncompressed, 'rb') as fun:
        while True:
            data = fun.read(BUF_SIZE)
            if not data:
                break
            md51.update(data)
    md52 = hashlib.md5()
    with gzip.open(compressed, 'rb') as fc:
        while True:
            data = fc.read(BUF_SIZE)
            if not data:
                break
            md52.update(data)
    return md51.digest() == md52.digest()


class Reader:
    '''Reader reads from files written by a Writer.

    Values are not converted from strings, you'll have to manage that yourself.
    Consider adding type information to the metadata in order to accomplish
    this.
    
    Metadata is loaded into the metadata attribute.

    Either use as an iterator over rows, or just call all_data. To load into a
    numpy array, use np.array(r.all_data()), np.loadtxt(r.datapath), or
    np.genfromtxt(r.datapath) as you like. Note that numpy places additional
    restrictions on datatypes and missing values that are not assumed by this
    database. In particular, I recommend storing column and type information in
    the metadata for more intelligent retrieval later.
    '''

    def __init__(self, basedir: str, id: int):
        basedir = os.path.expanduser(basedir)
        self.dir: str = os.path.join(basedir, str(id))
        self.datapath: str = os.path.join(self.dir, 'data.tsv.gz')
        self._data = gzip.open(self.datapath, 'rt')
        with open(os.path.join(self.dir, 'metadata.json')) as f:
            self.metadata: Dict = json.load(f)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self._data.close()

    def __iter__(self):
        self._data.seek(0)
        return csv.reader(self._data)

    def all_data(self) -> List[List[str]]:
        res = []
        self._data.seek(0)
        for row in csv.reader(self._data, delimiter='\t'):
            res.append(row)
        return res

    def blob(self, name) -> bytes:
        with open(os.path.join(self.dir, name), 'rb') as f:
            return f.read()


class Writer:
    '''Writer writes to files in a simple directory structure.

    The required input is a base directory path. The writer will create a new
    directory in this place if one does not exist already. The writer will then
    create a subdirectory with the lowest available integer name within the base
    directory. This is meant to represent one measurement, and is accessible
    through the dir attribute. The integer itself is available through the id
    attribute.

    Add data using either add_point or add_points. These will be stored in a
    gzipped TSV file called 'data.tsv.gz', accessible via the datapath
    attribute once the writer is closed. Before this point, they will be stored
    uncompressed in 'data.tsv'.

    (Nearly) arbitrary key/value pairs can be stored in the metadata attribute.
    This will be saved in JSON format in 'metadata.json', accessible via the
    metadatapath attribute. It is saved when the Writer is closed, and ignored
    after that point. I recommend saving column and type information into the
    metadata.

    Arbitrary bytes can be saved in the folder with add_blob.

    Either call close when complete, or else use as a context manager.
    '''

    def __init__(self, basedir: str, max_id: int=1000000, fsync_every=10):
        '''Create a Writer within basedir.

        If it can't find a valid id <= max_id, raises RuntimeError.
        '''

        basedir = os.path.expanduser(basedir)
        try:
            os.mkdir(basedir)
        except FileExistsError:
            pass

        # TODO: Do a binary search? Might get slow as the directory gets large.
        self.id: int = 0
        while self.id <= max_id:
            try:
                os.mkdir(os.path.join(basedir, str(self.id)))
                break
            except FileExistsError:
                self.id += 1
        if self.id == max_id + 1:
            raise RuntimeError('could not pick an id, hit the maximum')
        self.dir: str = os.path.join(basedir, str(self.id))

        self.datapath: str = os.path.join(self.dir, 'data.tsv')
        self._data = open(self.datapath, 'wt', newline='')
        self._writer = csv.writer(self._data, delimiter='\t')

        self.metadatapath: str = os.path.join(self.dir, 'metadata.json')
        self.metadata: Dict = {}

        self._fsync_every = fsync_every

        self._last_fsync = 0

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def close(self):
        with open(self.metadatapath, 'wt') as f:
            json.dump(self.metadata, f, indent=4)

        # Take care to flush and fsync the file before compression.
        self._data.flush()
        os.fsync(self._data.fileno())
        self._data.close()

        with open(self.datapath, 'rb') as f_in:
            with gzip.open(self.datapath + '.gz', 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
                f_out.flush()
                os.fsync(f_out.fileno())
        if not _files_equal(self.datapath, self.datapath + '.gz'):
            raise RuntimeError('compressed file not equal to uncompressed, '
                    'leaving both')
        # TODO: On Windows this will fail if any other program has the file
        # open, including if Dropbox is syncing it. Consider adding a retry or
        # something? idk
        try:
            os.remove(self.datapath)
        except Exception:
            pass
        self.datapath += '.gz'

    def add_points(self, points: List[List]):
        self._writer.writerows(points)
        self._last_fsync += len(points)
        if self._last_fsync >= self._fsync_every:
            self._last_fsync = 0
            self._data.flush()
            os.fsync(self._data.fileno())


    def add_point(self, point: List):
        self.add_points([point])

    def add_blob(self, name: str, data: bytes) -> str:
        if name in {'data.tsv', 'data.tsv.gz', 'metadata.json'}:
            raise ValueError(f'blob name cannot be {name}')

        blobpath = os.path.join(self.dir, name)
        with open(blobpath, 'wb') as f:
            f.write(data)
        return blobpath
