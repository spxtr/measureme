import os
import json
import numpy as np

'''
TODO:
- allow pload to pass metadata to pload0d, pload1d, and pload2d?
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
    

def pload(file_path: str, i: int):
    meta = load_meta(file_path, i)
    if meta['type'] == '0D':  
        return pload0d(file_path, i)
    elif meta['type'] == '1D':
        return pload1d(file_path, i)
    elif meta['type'] == '2D':
        return pload2d(file_path, i)
    

def pload0d(file_path: str, i: int):
    data = load(file_path, i)
    meta = load_meta(file_path, i)

    data_dict = {}
    if 'measurement_config' in meta:
        data_dict['measurement_config'] = meta['measurement_config']
    for ind, col in enumerate(meta['columns']):
        data_dict[col] = data[ind]
    return data_dict


def pload1d(file_path: str, i: int):
    data = load(file_path, i)
    meta = load_meta(file_path, i)

    data_dict = {}
    if 'measurement_config' in meta:
        data_dict['measurement_config'] = meta['measurement_config']
    if 'setpoints' in meta:
        data_dict['xs'] = np.array(meta['setpoints'])
    for ind, col in enumerate(meta['columns']):
        data_dict[col] = data[:, ind]
    return data_dict


def pload2d(file_path: str, i: int, pad_nan: bool=True):
    data = load(file_path, i)
    meta = load_meta(file_path, i)

    data_dict = {}
    if 'measurement_config' in meta:
        data_dict['measurement_config'] = meta['measurement_config']
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

