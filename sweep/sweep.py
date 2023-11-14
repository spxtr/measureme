import dataclasses
import functools
import os
import sys
import signal
import time
from typing import Callable, Dict, List, Union

from tqdm.auto  import tqdm
import logging

from IPython import display

import sweep.db
import sweep.plot

import numpy as np


BASEDIR = None
def set_basedir(path):
    global BASEDIR
    BASEDIR = path


def _sec_to_str(d):
    h, m, s = int(d/3600), int(d/60) % 60, int(d) % 60
    return f'{h}h {m}m {s}s'


def list_measurements(basedir=None):
    global BASEDIR
    if basedir is not None:
        path = basedir
    elif BASEDIR is not None:
        path = BASEDIR
    else:
        path = os.getcwd()

    def line(i, md):
        data = [str(i)]
        if 'start_time' in md:
            data.append(time.strftime('%Y-%b-%d %H:%M:%S', time.localtime(md['start_time'])))
        else:
            data.append('')
        if 'start_time' in md and 'end_time' in md:
            data.append(_sec_to_str(md['end_time'] - md['start_time']))
        else:
            data.append('')
        data.append(md['type'])
        data.append('yes' if md['interrupted'] else '')
        data.append(md['param'] if 'param' in md else '')
        data.append(md['slow_param'] if 'slow_param' in md else '')
        data.append(md['fast_param'] if 'fast_param' in md else '')
        return '|' + '|'.join(data) + '|'

    data = [
        '|ID|Start time|Duration|Type|Interrupted|Param|Slow param|Fast param|',
        '|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|',
    ]
    i = 0
    while True:
        try:
            with sweep.db.Reader(path, i) as r:
                data.append(line(i, r.metadata))
            i += 1
        except:
            break
    display.display_markdown('\n'.join(data), raw=True)


def measurement_info(i, basedir=None):
    global BASEDIR
    if basedir is not None:
        path = basedir
    elif BASEDIR is not None:
        path = BASEDIR
    else:
        path = os.getcwd()

    def format_list(l):
        newls = []
        if len(l) > 10:
            newls = l[:3] + ['...'] + l[-3:]
        else:
            newls = l
        return '[' + ', '.join([str(x) for x in newls]) + ']'

    with sweep.db.Reader(path, i) as r:
        print('ID:', i)
        print('Data path:', r.datapath)
        md = r.metadata
        if 'comments' in md:
            print('Comments:', md['comments'])
        if 'start_time' in md:
            print('Start time:', time.strftime('%Y-%b-%d %H:%M:%S', time.localtime(md['start_time'])))
        if 'start_time' in md and 'end_time' in md:
            print('Duration:', _sec_to_str(md['end_time'] - md['start_time']))
        print('Type:', md['type'])
        print('Interrupted:', 'yes' if md['interrupted'] else 'no')
        if 'param' in md:
            print('Param:', md['param'])
        if 'slow_param' in md:
            print('Slow param:', md['slow_param'])
        if 'fast_param' in md:
            print('Fast param:', md['slow_param'])
        if 'delay' in md:
            print('Delay:', md['delay'])
        if 'fast_delay' in md:
            print('Fast delay:', md['fast_delay'])
        if 'slow_delay' in md:
            print('Slow delay:', md['slow_delay'])
        print('Columns:', ', '.join(md['columns']))
        if 'setpoints' in md:
            print('Setpoints:', format_list(md['setpoints']))
        if 'slow_setpoints' in md:
            print('Slow setpoints:', format_list(md['slow_setpoints']))
        if 'fast_setpoints' in md:
            print('Fast setpoints:', format_list(md['fast_setpoints']))


@dataclasses.dataclass(repr=False)
class SweepResult:
    basedir:  str
    id:       int
    metadata: Dict
    datapath: str


def _interruptible(func):
    # We don't want to allow interrupts while communicating with
    # instruments. This checks for interrupts after measuring.
    # TODO: Allow potentially the param(setpoint) if possible.
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        args[0].interrupt_requested = False
        def handler(signum, frame):
            args[0].interrupt_requested = True
        old_handler = signal.signal(signal.SIGINT, handler)
        result = func(*args, **kwargs)
        signal.signal(signal.SIGINT, old_handler)
        return result
    return wrapper


class Station:
    '''A Station is a collection of parameters that can be measured.

    You can do 0D (measure), 1D (sweep), and 2D (megasweep) sweeps, and you can
    measure over time with watch.
    '''

    def __init__(self, basedir: str=None, verbose: bool=True):
        '''Create a Station.'''
        global BASEDIR
        if basedir is not None:
            self._basedir: str = basedir
        elif BASEDIR is not None:
            self._basedir: str = BASEDIR
        else:
            self._basedir: str = os.getcwd()

        self._verbose: bool = verbose
        self._init_logger()
        self._params: List = []
        self._plotter = sweep.plot.Plotter()
        self._run_befores = []
        self._run_afters = []
        self._comments = []
        self._interrupted = False
        self.logger.debug('Station initialized')

    def _init_logger(self):
        self.logger = logging.getLogger('sweep_log'+str(np.random.randint(2**31)))
        file_handler = logging.FileHandler(filename=os.path.join(self._basedir, 'log.log'))
        file_handler.setLevel(logging.DEBUG)
        
        stream_handler = logging.StreamHandler(sys.stdout)
        if self._verbose:
            stream_handler.setLevel(logging.INFO)
        else:
            stream_handler.setLevel(logging.WARNING)
            
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        file_handler.setFormatter(formatter)
        stream_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(stream_handler)
        self.logger.setLevel(logging.DEBUG)


    def add_comment(self, comment: str):
        self._comments.append(comment)


    def register_run_before(self, fn, args):
        self._run_befores.append((fn, args))


    def _run_run_befores(self):
        for fn, args in self._run_befores:
            fn(*args)


    def register_run_after(self, fn, args):
        self._run_afters.append((fn, args))


    def _run_run_afters(self):
        for fn, args in self._run_afters:
            fn(*args)


    def _measure(self) -> List[float]:
        return [p() / gain for p, gain in self._params]


    def _col_names(self) -> List[str]:
        return [p.full_name for p, _ in self._params]


    def follow_param(self, param, gain: float=1.0):
        self._params.append((param, gain))
        self.logger.debug(f'Follow paramter: {param.full_name}, gain: {gain}')
        return self


    fp = follow_param


    def plot(self, x, y, z=None):
        self._plotter.plot(x, y, z)


    def reset_plots(self):
        self._plotter.reset_plots()


    def reset(self):
        self._interrupted = False
        self.logger.debug(f'Reseting station')


    def _check_interrupted(self):
        if self._interrupted:
            raise InterruptedError('Station was previously interrupted, either remake it or use station.reset()')


    def _interruptable_sleep(self, delay):
        if delay <= 2:
            time.sleep(delay)
        else:
            t0 = time.time()
            while time.time()-t0 < delay:
                if self.interrupt_requested:
                    break
                time.sleep(0.1)

    
    def ramp(self, param, setpoint):
        cur_value = param()
        self.logger.info(f'Ramping {param.full_name}: {cur_value} -> {setpoint}')
        param(setpoint)


    def read(self, param, gain: float=1.0):
        val = param()/gain
        self.logger.info(f'Reading {param.full_name}: {val}')

    
    def read_all(self):
         self.logger.info(f'Reading all parameters:')
         [self.read(p, gain=gain) for p, gain in self._params]


    def measure(self):
        self._check_interrupted()
        with sweep.db.Writer(self._basedir) as w:
            self.logger.info(f'Starting measure with ID {w.id}')
            w.metadata['comments'] = self._comments
            w.metadata['type'] = '0D'
            w.metadata['columns'] = ['time'] + self._col_names()
            t = time.time()
            w.metadata['time'] = t
            w.update_metadata()

            self._run_run_befores()
            w.add_point([t] + self._measure())
            self._run_run_afters()
        self.logger.info(f'Data saved in {w.datapath}')
        return SweepResult(self._basedir, w.id, w.metadata, w.datapath)


    @_interruptible
    def watch(self, delay: float=0.0, max_duration=None):
        self._check_interrupted()
        with sweep.db.Writer(self._basedir) as w, self._plotter as p:
            self.logger.info(f'Starting watch with ID {w.id}')
            w.metadata['comments'] = self._comments
            w.metadata['type'] = '1D'
            w.metadata['delay'] = delay
            w.metadata['max_duration'] = max_duration
            w.metadata['columns'] = ['time'] + self._col_names()
            w.metadata['interrupted'] = False
            w.metadata['start_time'] = time.time()
            p.set_cols(w.metadata['columns'])
            w.update_metadata()

            t_start = time.monotonic() # Can't go backwards!
            while max_duration is None or time.monotonic() - t_start < max_duration:
                time.sleep(delay)
                self._run_run_befores()
                data = [time.time()] + self._measure()
                w.add_point(data)
                p.add_point(data)

                if self.interrupt_requested:
                    self.logger.warning(f'ID {w.id} INTERRUPTED')
                    self._interrupted = True
                    w.metadata['interrupted'] = True
                    break

                self._run_run_afters()
            w.metadata['end_time'] = time.time()
            image = p.send_image()
            if image is not None:
                w.add_blob('plot.png', image)
                display.display(display.Image(data=image, format='png'))
        duration = w.metadata['end_time'] - w.metadata['start_time']
        self.logger.info(f'Completed in {_sec_to_str(duration)}')
        self.logger.info(f'Data saved in {w.datapath}')

        return SweepResult(self._basedir, w.id, w.metadata, w.datapath)


    @_interruptible
    def sweep(self, param, setpoints, delay: float=0.0):
        self._check_interrupted()
        with sweep.db.Writer(self._basedir) as w, self._plotter as p:
            self.logger.info(f'Starting sweep with ID {w.id}')
            self.logger.debug(f'Sweeping: {param.full_name}')
            self.logger.info(f'Minimum duration {_sec_to_str(len(setpoints) * delay)}')

            w.metadata['comments'] = self._comments
            w.metadata['type'] = '1D'
            w.metadata['delay'] = delay
            w.metadata['param'] = param.full_name
            w.metadata['columns'] = ['time', param.full_name] + self._col_names()
            w.metadata['setpoints'] = list(setpoints)
            w.metadata['interrupted'] = False
            w.metadata['start_time'] = time.time()
            p.set_cols(w.metadata['columns'])
            w.update_metadata()

            for setpoint in tqdm(setpoints):
                param(setpoint)
                time.sleep(delay)
                self._run_run_befores()
                data = [time.time(), setpoint] + self._measure()
                w.add_point(data)
                p.add_point(data)

                if self.interrupt_requested:
                    self.logger.warning(f'ID {w.id} INTERRUPTED')
                    self._interrupted = True
                    w.metadata['interrupted'] = True
                    break

                self._run_run_afters()
            w.metadata['end_time'] = time.time()
            image = p.send_image()
            if image is not None:
                w.add_blob('plot.png', image)
                display.display(display.Image(data=image, format='png'))

        duration = w.metadata['end_time'] - w.metadata['start_time']
        self.logger.info(f'Completed in {_sec_to_str(duration)}')
        self.logger.info(f'Data saved in {w.datapath}')

        return SweepResult(self._basedir, w.id, w.metadata, w.datapath)


    @_interruptible
    def multisweep(self, params, setpointslist, delay: float=0.0):
        self._check_interrupted()
        if not all(len(l) == len(setpointslist[0]) for l in setpointslist):
            raise ValueError('not all setpoint lists have same length!')

        setpoints = [list(i) for i in zip(*setpointslist)]
        with sweep.db.Writer(self._basedir) as w, self._plotter as p:
            self.logger.info(f'Starting multisweep with ID {w.id}')
            paramlist = []
            for param in params:
                paramlist.append(param.full_name)
            self.logger.debug(f'Sweeping: {paramlist}')
            self.logger.info(f'Minimum duration {_sec_to_str(len(setpoints) * delay)}')

            w.metadata['comments'] = self._comments
            w.metadata['type'] = '1D'
            w.metadata['delay'] = delay
            w.metadata['param'] = paramlist
            w.metadata['columns'] = ['time'] + [param for param in paramlist] + self._col_names()
            w.metadata['setpoints'] = [list(sps) for sps in setpointslist]
            w.metadata['interrupted'] = False
            w.metadata['start_time'] = time.time()
            p.set_cols(w.metadata['columns'])
            w.update_metadata()

            for setpoint in tqdm(setpoints):
                for param, sp in zip(params, setpoint):
                    param(sp)
                time.sleep(delay)
                self._run_run_befores()
                data = [time.time()] + setpoint + self._measure()
                w.add_point(data)
                p.add_point(data)

                if self.interrupt_requested:
                    self.logger.warning(f'ID {w.id} INTERRUPTED')
                    self._interrupted = True
                    w.metadata['interrupted'] = True
                    break

                self._run_run_afters()
            w.metadata['end_time'] = time.time()
            image = p.send_image()
            if image is not None:
                w.add_blob('plot.png', image)
                display.display(display.Image(data=image, format='png'))

        duration = w.metadata['end_time'] - w.metadata['start_time']
        self.logger.info(f'Completed in {_sec_to_str(duration)}')
        self.logger.info(f'Data saved in {w.datapath}')

        return SweepResult(self._basedir, w.id, w.metadata, w.datapath)


    @_interruptible
    def megasweep(self, slow_param, slow_v, fast_param, fast_v, 
                  slow_delay: float=0.0, fast_delay: float=0.0, init_delay=True):
        self._check_interrupted()
        with sweep.db.Writer(self._basedir) as w, self._plotter as p:
            self.logger.info(f'Starting megasweep with ID {w.id}')
            self.logger.debug(f'Slow: {slow_param.full_name}, Fast: {fast_param.full_name}')
            min_duration = len(slow_v) * len(fast_v) * fast_delay + len(slow_v) * slow_delay
            self.logger.info(f'Minimum duration {_sec_to_str(min_duration)}')

            w.metadata['comments'] = self._comments
            w.metadata['type'] = '2D'
            w.metadata['slow_delay'] = slow_delay
            w.metadata['fast_delay'] = fast_delay
            w.metadata['slow_param'] = slow_param.full_name
            w.metadata['fast_param'] = fast_param.full_name
            w.metadata['columns'] = ['time', slow_param.full_name, fast_param.full_name] + self._col_names()
            w.metadata['slow_setpoints'] = list(slow_v)
            w.metadata['fast_setpoints'] = list(fast_v)
            w.metadata['interrupted'] = False
            w.metadata['start_time'] = time.time()
            p.set_cols(w.metadata['columns'])
            w.update_metadata()

            for i, ov in enumerate(tqdm(slow_v, position=0)):
                self.logger.debug(f'{i+1}/{len(slow_v)}: {slow_param.full_name }= {ov}')
                slow_param(ov)
                if not init_delay and i==0:
                    pass
                else:
                    self._interruptable_sleep(slow_delay)

                if self.interrupt_requested:
                    self.logger.warning(f'ID {w.id} INTERRUPTED')
                    self._interrupted = True
                    w.metadata['interrupted'] = True
                    break
                        
                for iv in tqdm(fast_v, position=1, leave=False):
                    fast_param(iv)
                    time.sleep(fast_delay)
                    self._run_run_befores()
                    data = [time.time(), ov, iv] + self._measure()
                    w.add_point(data)
                    p.add_point(data)

                    if self.interrupt_requested:
                        self.logger.warning(f'ID {w.id} INTERRUPTED')
                        self._interrupted = True
                        w.metadata['interrupted'] = True
                        break

                    self._run_run_afters()

                if self.interrupt_requested:
                    self.logger.warning(f'ID {w.id} INTERRUPTED')
                    self._interrupted = True
                    w.metadata['interrupted'] = True
                    break

            w.metadata['end_time'] = time.time()
            image = p.send_image()
            if image is not None:
                w.add_blob('plot.png', image)
                display.display(display.Image(data=image, format='png'))

        duration = w.metadata['end_time'] - w.metadata['start_time']
        self.logger.info(f'Completed in {_sec_to_str(duration)}')
        self.logger.info(f'Data saved in {w.datapath}')

        return SweepResult(self._basedir, w.id, w.metadata, w.datapath)


    @_interruptible
    def multimegasweep(self, slow_params, slow_v_list, fast_params, fast_v_list, 
                       slow_delay: float=0.0, fast_delay: float=0.0, init_delay=True):
        self._check_interrupted()
        if not all(len(l) == len(fast_v_list[0]) for l in fast_v_list):
            raise ValueError('not all fast axis setpoint lists have same length!')
        if not all(len(l) == len(slow_v_list[0]) for l in slow_v_list):
            raise ValueError('not all slow axis setpoint lists have same length!')

        slow_vs = [list(i) for i in zip(*slow_v_list)]
        fast_vs = [list(i) for i in zip(*fast_v_list)]

        with sweep.db.Writer(self._basedir) as w, self._plotter as p:
            self.logger.info(f'Starting multimegasweep with ID {w.id}')
            slowparamlist = []
            for param in slow_params:
                slowparamlist.append(param.full_name)

            fastparamlist = []
            for param in fast_params:
                fastparamlist.append(param.full_name)

            self.logger.debug(f'Slows: {slowparamlist}, Fasts: {fastparamlist}')
            min_duration = len(slow_vs) * len(fast_vs) * fast_delay + len(slow_vs) * slow_delay
            self.logger.info(f'Minimum duration {_sec_to_str(min_duration)}')

            w.metadata['comments'] = self._comments
            w.metadata['type'] = '2D'
            w.metadata['slow_delay'] = slow_delay
            w.metadata['fast_delay'] = fast_delay
            w.metadata['slow_param'] = slowparamlist
            w.metadata['fast_param'] = fastparamlist
            w.metadata['columns'] = ['time'] + [param for param in slowparamlist] + [param for param in fastparamlist] + self._col_names()
            w.metadata['slow_setpoints'] = [list(sps) for sps in slow_v_list]
            w.metadata['fast_setpoints'] = [list(sps) for sps in fast_v_list]
            w.metadata['interrupted'] = False
            w.metadata['start_time'] = time.time()
            p.set_cols(w.metadata['columns'])
            w.update_metadata()

            for i, slow_v in enumerate(tqdm(slow_vs, position=0)):
                self.logger.debug(f'{i+1}/{len(slow_vs)}: {slowparamlist} = {slow_v}')
                for slow_param, ov in zip(slow_params, slow_v):
                    slow_param(ov)
                if not init_delay and i==0:
                    pass
                else:
                    self._interruptable_sleep(slow_delay)
                    
                if self.interrupt_requested:
                    self.logger.warning(f'ID {w.id} INTERRUPTED')
                    self._interrupted = True
                    w.metadata['interrupted'] = True
                    break
                    
                for fast_v in tqdm(fast_vs, position=1, leave=False):
                    for fast_param, iv in zip(fast_params, fast_v):
                        fast_param(iv)
                    time.sleep(fast_delay)
                    self._run_run_befores()
                    data = [time.time()] + slow_v + fast_v + self._measure()
                    w.add_point(data)
                    p.add_point(data)

                    if self.interrupt_requested:
                        self.logger.warning(f'ID {w.id} INTERRUPTED')
                        self._interrupted = True
                        w.metadata['interrupted'] = True
                        break

                    self._run_run_afters()

                if self.interrupt_requested:
                    self.logger.warning(f'ID {w.id} INTERRUPTED')
                    self._interrupted = True
                    w.metadata['interrupted'] = True
                    break

            w.metadata['end_time'] = time.time()
            image = p.send_image()
            if image is not None:
                w.add_blob('plot.png', image)
                display.display(display.Image(data=image, format='png'))

        duration = w.metadata['end_time'] - w.metadata['start_time']
        self.logger.info(f'Completed in {_sec_to_str(duration)}')
        self.logger.info(f'Data saved in {w.datapath}')

        return SweepResult(self._basedir, w.id, w.metadata, w.datapath)
