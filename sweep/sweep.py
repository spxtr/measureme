import dataclasses
import functools
import os
import signal
import time
import json
from typing import Callable, Dict, List, Union

from IPython import display

import sweep.db
import sweep.plot


BASEDIR = None


def set_basedir(path):
    global BASEDIR
    BASEDIR = path


def _sec_to_str(d):
    h, m, s = int(d/3600), int(d/60) % 60, int(d) % 60
    return f'{h}h {m}m {s}s'


@dataclasses.dataclass(repr=False)
class SweepResult:
    basedir:  str
    id:       int
    metadata: Dict
    datapath: str


def _interruptible(func):
    # We don't want to allow interrupts while communicating with
    # instruments. This checks for interrupts after measuring.
    # TODO: Allow interrupting the time.sleep() somehow, and potentially
    #       also the param(setpoint) if possible.
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

    def __init__(self, basedir: str = None, verbose: bool = True):
        '''Create a Station.'''
        global BASEDIR
        if basedir is not None:
            self._basedir: str = basedir
        elif BASEDIR is not None:
            self._basedir: str = BASEDIR
        else:
            self._basedir: str = os.getcwd()

        self._verbose: bool = verbose
        self._params: List = []
        self._plotter = sweep.plot.Plotter()

    def _measure(self) -> List[float]:
        return [p() / gain for p, gain in self._params]

    def _col_names(self) -> List[str]:
        return [p.full_name for p, _ in self._params]

    def follow_param(self, param, gain: float = 1.0):
        self._params.append((param, gain))
        return self

    fp = follow_param

    def _print(self, msg):
        if self._verbose:
            print(msg)

    def plot(self, x, y, z=None):
        self._plotter.plot(x, y, z)

    def reset_plots(self):
        self._plotter.reset_plots()

    def measure(self):
        with sweep.db.Writer(self._basedir) as w:
            w.metadata['type'] = '0D'
            w.metadata['columns'] = ['time'] + self._col_names()
            t = time.time()
            w.metadata['time'] = t
            w.add_point([t] + self._measure())
        self._print(f'Data saved in {w.datapath}')
        return SweepResult(self._basedir, w.id, w.metadata, w.datapath)

    @_interruptible
    def watch(self, delay: float = 0.0, max_duration=None, user_metadata=None):
        with sweep.db.Writer(self._basedir) as w, self._plotter as p:
            self._print(f'Starting run with ID {w.id}')
            w.metadata['type'] = '1D'
            w.metadata['delay'] = delay
            w.metadata['max_duration'] = max_duration
            w.metadata['columns'] = ['time'] + self._col_names()
            w.metadata['interrupted'] = False
            w.metadata['start_time'] = time.time()
            p.set_cols(w.metadata['columns'])
            t_start = time.monotonic()  # Can't go backwards!
            while max_duration is None or time.monotonic() - t_start < max_duration:
                time.sleep(delay)
                data = [time.time()] + self._measure()
                w.add_point(data)
                p.add_point(data)
                if self.interrupt_requested:
                    w.metadata['interrupted'] = True
                    break
            w.metadata['end_time'] = time.time()

            if user_metadata is not None:
                w.add_blob('user_metadata.json', json.dumps(user_metadata))

            image = p.send_image()
            if image is not None:
                w.add_blob('plot.png', image)
                display.display(display.Image(data=image, format='png'))
        duration = w.metadata['end_time'] - w.metadata['start_time']
        self._print(f'Completed in {_sec_to_str(duration)}')
        self._print(f'Data saved in {w.datapath}')

        return SweepResult(self._basedir, w.id, w.metadata, w.datapath)

    @_interruptible
    def sweep(self, param, setpoints, delay: float = 0.0, user_metadata=None):
        with sweep.db.Writer(self._basedir) as w, self._plotter as p:
            self._print(f'Starting run with ID {w.id}')
            self._print(
                f'Minimum duration {_sec_to_str(len(setpoints) * delay)}')

            w.metadata['type'] = '1D'
            w.metadata['delay'] = delay
            w.metadata['param'] = param.full_name
            w.metadata['columns'] = [
                'time', param.full_name] + self._col_names()
            w.metadata['setpoints'] = list(setpoints)
            w.metadata['interrupted'] = False
            w.metadata['start_time'] = time.time()
            p.set_cols(w.metadata['columns'])

            for setpoint in setpoints:
                param(setpoint)
                time.sleep(delay)  # TODO: Account for time spent in between?
                data = [time.time(), setpoint] + self._measure()
                w.add_point(data)
                p.add_point(data)
                if self.interrupt_requested:
                    w.metadata['interrupted'] = True
                    break

            w.metadata['end_time'] = time.time()

            if user_metadata is not None:
                w.add_blob('user_metadata.json', json.dumps(user_metadata))

            image = p.send_image()
            if image is not None:
                w.add_blob('plot.png', image)
                display.display(display.Image(data=image, format='png'))

        duration = w.metadata['end_time'] - w.metadata['start_time']
        self._print(f'Completed in {_sec_to_str(duration)}')
        self._print(f'Data saved in {w.datapath}')

        return SweepResult(self._basedir, w.id, w.metadata, w.datapath)

    @_interruptible
    def megasweep(self, slow_param, slow_v, fast_param, fast_v, slow_delay=0, fast_delay=0, user_metadata=None):
        with sweep.db.Writer(self._basedir) as w, self._plotter as p:
            self._print(f'Starting run with ID {w.id}')
            min_duration = len(slow_v) * len(fast_v) * \
                fast_delay + len(slow_v) * slow_delay
            self._print(f'Minimum duration {_sec_to_str(min_duration)}')

            w.metadata['type'] = '2D'
            w.metadata['slow_delay'] = slow_delay
            w.metadata['fast_delay'] = slow_delay
            w.metadata['slow_param'] = slow_param.full_name
            w.metadata['fast_param'] = fast_param.full_name
            w.metadata['columns'] = ['time', slow_param.full_name,
                                     fast_param.full_name] + self._col_names()
            w.metadata['slow_setpoints'] = list(slow_v)
            w.metadata['fast_setpoints'] = list(fast_v)
            w.metadata['interrupted'] = False
            w.metadata['start_time'] = time.time()
            p.set_cols(w.metadata['columns'])

            for ov in slow_v:
                slow_param(ov)
                time.sleep(slow_delay)
                for iv in fast_v:
                    fast_param(iv)
                    time.sleep(fast_delay)
                    data = [time.time(), ov, iv] + self._measure()
                    w.add_point(data)
                    p.add_point(data)
                    if self.interrupt_requested:
                        w.metadata['interrupted'] = True
                        break
                if self.interrupt_requested:
                    break

            w.metadata['end_time'] = time.time()

            if user_metadata is not None:
                w.add_blob('user_metadata.json', json.dumps(user_metadata))

            image = p.send_image()
            if image is not None:
                w.add_blob('plot.png', image)
                display.display(display.Image(data=image, format='png'))

        duration = w.metadata['end_time'] - w.metadata['start_time']
        self._print(f'Completed in {_sec_to_str(duration)}')
        self._print(f'Data saved in {w.datapath}')

        return SweepResult(self._basedir, w.id, w.metadata, w.datapath)
