import io
import time
import collections
import math
import socket
import functools
import multiprocessing

import numpy as np
import scipy
from scipy.interpolate import griddata
import matplotlib
matplotlib.use('Qt5Agg')
import matplotlib.pyplot as plt
from IPython import display
import qcodes as qc
from qcodes.dataset.measurements import Measurement
from qcodes.instrument_drivers.stanford_research.SR830 import SR830
from qcodes.instrument.specialized_parameters import ElapsedTimeParameter


def _sec_to_str(d):
    h, m, s = int(d/3600), int(d/60) % 60, int(d) % 60
    return f'{h}h {m}m {s}s'


_Param = collections.namedtuple('_Param', ['param', 'gain'])
_SR830 = collections.namedtuple('_SR830', ['sr830', 'gain', 'autorange'])
_FBL   = collections.namedtuple('_FBL',   ['host', 'port', 'channels', 'gains'])
_Fn    = collections.namedtuple('_Fn',    ['fn', 'gain', 'name', 'unit'])


class _Plotter:
    def __init__(self):
        pass
    
    def start(self, plots):
        self._plots = plots
        rows = math.ceil(len(plots) / 4)
        cols = len(plots) % 4 if len(plots) < 4 else 4
        self._fig = plt.figure(figsize=(4 * cols, 4 * rows))
        grid = plt.GridSpec(rows, cols)
        self._lines = []
        self._axs = []
        for i, (xs, ys, zs) in enumerate(plots):
            if len(zs) == 0:
                ax = self._fig.add_subplot(grid[i // 4, i % 4])
                ax.set_xlabel(xs[0])
                for y in ys:
                    self._lines.append((xs[0], y, ax.plot([], [], label=y)[0]))
                if len(ys) == 1:
                    ax.set_ylabel(ys[0])
                else:
                    ax.legend()
                self._axs.append(ax)
        self._fig.show()
    
    def stop(self):
        plt.close(self._fig)
    
    def add_points(self, points):
        for point in points:
            for x, y, line in self._lines:
                line.set_xdata(np.append(line.get_xdata(), point[x]))
                line.set_ydata(np.append(line.get_ydata(), point[y]))
        for ax in self._axs:
            ax.relim()
            ax.autoscale_view()
        self._fig.tight_layout()
        self._fig.canvas.draw()
    
    def image(self):
        b = io.BytesIO()
        self._fig.savefig(b, format='png')
        return b

def _plot_loop(conn):
    p = _Plotter()
    quit = False
    while not quit:
        messages = []
        while conn.poll():
            messages.append(conn.recv())
        data = []
        send = False
        for m in messages:
            if m['action'] == 'stop':
                quit = True
            elif m['action'] == 'start':
                p.start(m['plots'])
            elif m['action'] == 'add_point':
                data.append(m['data'])
            elif m['action'] == 'send_data':
                send = True
        if len(data) > 0:
            p.add_points(data)
        if send:
            conn.send(p.image())
        if quit:
            p.stop()
            return
        plt.pause(0.1)
            
            
def _with_live_plotting(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        parent_pipe, child_pipe = multiprocessing.Pipe()
        proc = multiprocessing.Process(target=_plot_loop, args=(child_pipe,))
        proc.start()
        args[0]._plot_conn = parent_pipe
        parent_pipe.send({
            'action': 'start',
            'plots': args[0]._plots,
        })
        func(*args, **kwargs)
        parent_pipe.send({'action': 'send_data'})
        display.display(display.Image(data=parent_pipe.recv().getbuffer(), format='png'))
        parent_pipe.send({'action': 'stop'})
        proc.join()
    return wrapper


# Decorator for sweep-like functions.
# This will both time the function and catch KeyboardInterrupt.
def _interruptible(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        t0 = time.monotonic()
        try:
            func(*args, **kwargs)
        except KeyboardInterrupt:
            print('Interrupted.')
        print(f'Completed in {_sec_to_str(time.monotonic() - t0)}.')
    return wrapper


# Decorator that creates and connects self._fbl_sock, then cleans it up at the end.
def _with_fbl_socket(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        sweep = args[0]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if sweep._fbl is not None:
                s.connect((sweep._fbl.host, sweep._fbl.port))
                sweep._fbl_sock = s
            func(*args, **kwargs)
    return wrapper


class Sweep:
    """Perform measurement sweeps of various kinds.
    
    You will want to use the various follow_* functions to add parameters to follow,
    then call one of the sweep functions. You can reuse the same Sweep object for
    multiple sweeps.
    """
    def __init__(self):
        self._params = []
        self._sr830s = []
        self._fbl = None
        self._fbl_sock = None
        self._fns = []
        self._etp = None
        self._plots = []
     
    def follow_param(self, param, gain=1.0):
        """Follow a qcodes Parameter."""
        if not isinstance(param, qc.Parameter):
            raise ValueError(f'param is not a qcodes Parameter, it is a {type(param)}')
        self._params.append(_Param(param, gain))
        return self
         
    def follow_sr830(self, sr830, gain=1.0, autorange=True):
        """Follow an SR830."""
        if not isinstance(sr830, SR830):
            raise ValueError(f'sr830 is not a qcodes SR830, it is a {type(sr830)}')
        self._sr830s.append(_SR830(sr830, gain, autorange))
        return self
    
    def follow_fbl(self, channels, host='localhost', port=10000, gains=None):
        if self._fbl is not None:
            raise Exception('cannot follow_fbl twice, please do it in one call')
        if gains is None:
            gains = np.ones(len(channels))
        elif len(gains) != len(channels):
            raise ValueError(f'different number of gains ({len(gains)}) and channels ({len(channels)})')
        self._fbl = _FBL(host, port, channels, gains)
        return self
            
 
    def follow_fn(self, fn, name, gain=1.0, unit=None):
        """Follow an arbitrary function.
        
        The function will be passed a dictionary containing mappings of
        parameter.full_name -> value for each parameter. Your function should return
        one number.
        """
        self._fns.append(_Fn(fn, gain, name, unit))
        return self
     
    def _autorange_sr830(self, sr830, max_changes=3):
        def autorange_once():
            r = sr830.R.get()
            sens = sr830.sensitivity.get()
            if r > 0.9 * sens:
                return sr830.increment_sensitivity()
            elif r < 0.1 * sens:
                return sr830.decrement_sensitivity()
            return False
        sets = 0
        while autorange_once() and sets < max_changes:
            sets += 1
            # Sleep 10 times the time constant between range sets.
            # The manual has more detailed guidelines for how long to wait.
            time.sleep(10 * sr830.time_constant.get())
 
    def _create_measurement(self, *set_params):
        meas = Measurement()
        self._etp = ElapsedTimeParameter('time')
        meas.register_parameter(self._etp)
        for param in set_params:
            meas.register_parameter(param)
        for param in self._params:
            meas.register_parameter(param.param, setpoints=(*set_params, self._etp))
        for sr830 in self._sr830s:
            meas.register_parameter(sr830.sr830.X, setpoints=(*set_params, self._etp))
            meas.register_parameter(sr830.sr830.Y, setpoints=(*set_params, self._etp))
        if self._fbl is not None:
            for c in self._fbl.channels:
                meas.register_custom_parameter(f'fbl_c{c}_r', setpoints=(*set_params, self._etp))
                meas.register_custom_parameter(f'fbl_c{c}_p', setpoints=(*set_params, self._etp))
                meas.register_custom_parameter(f'fbl_c{c}_o', setpoints=(*set_params, self._etp))
                meas.register_custom_parameter(f'fbl_c{c}_s', setpoints=(*set_params, self._etp))
        for fn in self._fns:
            meas.register_custom_parameter(fn.name, setpoints=(*set_params, self._etp))
        return meas
     
    def _measure_param(self, param):
        return param.param() / param.gain
     
    def _measure_sr830(self, sr830):
        if sr830.autorange:
            self._autorange_sr830(sr830.sr830)
        # Snap grabs both x and y simultaneously.
        # Grabbing them separately may bias results.
        x, y = sr830.sr830.snap('x', 'y')
        return x / sr830.gain, y / sr830.gain
    
    def _measure_fbl(self):
        if self._fbl is None:
            return []
        self._fbl_sock.sendall(b'send_data\n')
        recv = self._fbl_sock.recv(8*32*4) # Double precision (8), 32 channels, 4 variables.
        arr = np.frombuffer(recv, dtype=np.float64).reshape(32, 4, order='F')
        data = []
        for c, g in zip(self._fbl.channels, self._fbl.gains):
            data.append((f'fbl_c{c}_o', arr[c,0] / g))
            data.append((f'fbl_c{c}_s', arr[c,1] / g))
            data.append((f'fbl_c{c}_r', arr[c,2] / g))
            data.append((f'fbl_c{c}_p', arr[c,3] / g))
        return data
    
    def _measure_inputs(self):
        data = [(self._etp, self._etp())]
        for param in self._params:
            data.append([param.param, self._measure_param(param)])
        for sr830 in self._sr830s:
            x, y = self._measure_sr830(sr830)
            data.extend([[sr830.sr830.X, x], [sr830.sr830.Y, y]])
        data.extend(self._measure_fbl())
        return data
    
    def _format_data_map(self, data):
        m = {}
        for p, v in data:
            if isinstance(p, str):
                m[p] = v
            else:
                m[p.full_name] = v
        return m

    def _call_fns(self, data):
        fn_input = self._format_data_map(data)
        fn_data = []
        for fn in self._fns:
            fn_data.append([fn.name, fn.fn(fn_input) / fn.gain])
        return fn_data
    
    def _send_plot_data(self, data):
        self._plot_conn.send({
            'action': 'add_point',
            'data': self._format_data_map(data)
        })
        
    def plot(self, x=None, y=None, z=None):
        if isinstance(x, list):
            raise ValueError('don''t put multiple xs you goofus')
        if x is None or y is None:
            raise ValueError('x and y cannot be empty')
        if z is not None:
            raise ValueError('2D plots not supported rn')
        def to_names(v):
            if v is None:
                return []
            def n(p):
                if isinstance(p, str):
                    return p
                return p.full_name
            if isinstance(v, list):
                nl = []
                for item in v:
                    nl.append(n(item))
                return nl
            return [n(v)]
        self._plots.append((to_names(x), to_names(y), to_names(z)))

    @_with_live_plotting
    @_interruptible
    @_with_fbl_socket
    def sweep(self, set_param, vals, inter_delay=0):
        print(f'Minimum duration: {_sec_to_str(len(vals) * inter_delay)}')
        meas = self._create_measurement(set_param)
        with meas.run() as datasaver:
            for setpoint in vals:
                set_param.set(setpoint)
                time.sleep(inter_delay)
                data = [(set_param, setpoint)]
                data.extend(self._measure_inputs())
                data.extend(self._call_fns(data))
                datasaver.add_result(*data)
                self._send_plot_data(data)
            self.dataset = datasaver.dataset
 
    @_with_live_plotting
    @_interruptible
    @_with_fbl_socket
    def watch(self, inter_delay=0, max_duration=None):
        meas = self._create_measurement()
        with meas.run() as datasaver:
            self._etp.reset_clock()
            while max_duration is None or self._etp() < max_duration:
                time.sleep(inter_delay)
                data = self._measure_inputs()
                data.extend(self._call_fns(data))
                datasaver.add_result(*data)
                self._send_plot_data(data)
            self.dataset = datasaver.dataset

    @_with_live_plotting
    @_interruptible
    @_with_fbl_socket
    def megasweep(self, slow_p, slow_v, fast_p, fast_v, slow_delay=0, fast_delay=0):
        print(f'Minimum duration: {_sec_to_str(len(slow_v)*len(fast_v)*fast_delay + len(slow_v)*slow_delay)}')
        meas = self._create_measurement(slow_p, fast_p)
        with meas.run() as datasaver:
            for ov in slow_v:
                slow_p.set(ov)
                time.sleep(slow_delay)
                for iv in fast_v:
                    fast_p.set(iv)
                    time.sleep(fast_delay)
                    data = [(slow_p, ov), (fast_p, iv)]
                    data.extend(self._measure_inputs())
                    data.extend(self._call_fns(data))
                    datasaver.add_result(*data)
                    self._send_plot_data(data)
            self.dataset = datasaver.dataset
