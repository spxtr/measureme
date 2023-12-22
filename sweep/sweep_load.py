import os
import json
import numpy as np

'''
TODO:
- make pload smarter about data type
- Fix when trying to pload data without setpoints (eg watch)
- Maybe make meta data contain function call type
'''

def load_meta(file_path: str, i: int):
    fp = open(os.path.join(file_path, str(i), r'metadata.json'), 'r')
    return json.load(fp)


def load(file_path: str, i: int):
    path = os.path.join(file_path, str(i), '')
    if os.path.isfile(path + r'data.tsv.gz'):
        return np.loadtxt(path + r'data.tsv.gz')
    else:
        return np.loadtxt(path + r'data.tsv')


def pload1d(file_path: str, i: int):
    data = load(file_path, i)
    meta = load_meta(file_path, i)

    data_dict = {}
    data_dict['xs'] = np.array(meta['setpoints'])
    for ind, col in enumerate(meta['columns']):
        data_dict[col] = data[:, ind]
    return data_dict


def pload2d(file_path: str, i: int, pad_nan: bool=True):
    data = load(file_path, i)
    meta = load_meta(file_path, i)

    data_dict = {}
    data_dict['xs'] = np.array(meta['fast_setpoints'])
    data_dict['ys'] = np.array(meta['slow_setpoints'])
    lenx = np.shape(meta['fast_setpoints'])[-1]
    leny = np.shape(meta['slow_setpoints'])[-1]
    for ind, col in enumerate(meta['columns']):
        d = data[:, ind]
        if pad_nan:
            data_dict[col] = np.pad(d, (0, lenx*leny - len(d)), 
                                    'constant', constant_values=(np.NAN, np.NAN)).reshape((leny, lenx))
        else:
            data_dict[col] = np.pad(d, (0, lenx*leny - len(d))).reshape((leny, lenx))
    return data_dict

