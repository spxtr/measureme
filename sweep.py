%matplotlib qt
import io
import time
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter
import qcodes as qc
from qcodes.dataset.measurements import Measurement
from IPython import display
from qcodes.instrument_drivers.stanford_research.SR830 import SR830

def _autorange_srs(srs, max_changes=1):
    def autorange_once():
        r = srs.R.get()
        sens = srs.sensitivity.get()
        if r > 0.9 * sens:
            return srs.increment_sensitivity()
        elif r < 0.1 * sens:
            return srs.decrement_sensitivity()
        return False
    sets = 0
    while autorange_once() and sets < max_changes:
        sets += 1
        time.sleep(10*srs.time_constant.get())

class Sweep(object):
    def __init__(self):
        self._sr830s = []
        self._params = []
        self._fbl = None
        self._fbl_channels = []
    
    def follow_param(self, p, gain=1.0):
        self._params.append((p, gain))

    def follow_sr830(self, l, name=None, gain=1.0):
        self._sr830s.append((l, name, gain))
        
    def follow_fbl(self, fbl, channels):
        self._fbl = fbl
        self._fbl_channels = channels

    def _create_measurement(self, *set_params):
        meas = Measurement()
        for p in set_params:
            meas.register_parameter(p)
        meas.register_custom_parameter('time', label='Time', unit='s')
        for p, _ in self._params:
            meas.register_parameter(p, setpoints=(*set_params, 'time',))
        for l, _, _ in self._sr830s:
            meas.register_parameter(l.X, setpoints=(*set_params, 'time',))
            meas.register_parameter(l.Y, setpoints=(*set_params, 'time',))
        for c in self._fbl_channels:
            meas.register_custom_parameter(f'fbl_c{c}_r', label=f'FBL Channel {c} Amplitude', unit='V')
            meas.register_custom_parameter(f'fbl_c{c}_p', label=f'FBL Channel {c} Phase', unit='deg')
        return meas

    def _prepare_1d_plots(self, set_param=None):
        if set_param is None:
            self._setaxs = 0
            set_lbl = 'Time (s)'
        else:
            self._setaxs = 1
            set_lbl = f'{set_param.label} ({set_param.unit})'
        self._fig = plt.figure(figsize=(4*(self._setaxs + 1 + len(self._params) + len(self._sr830s) + len(self._fbl_channels)),4))
        grid = plt.GridSpec(4, self._setaxs + len(self._params) + len(self._sr830s) + len(self._fbl_channels), hspace=0)
        if set_param is not None:
            self._setax = self._fig.add_subplot(grid[:, 0])
            self._setax.set_xlabel('Time (s)')
            self._setax.set_ylabel(set_lbl)
            self._setaxline = self._setax.plot([], [])[0]

        self._paxs = []
        self._plines = []
        for i, (p, _) in enumerate(self._params):
            ax = self._fig.add_subplot(grid[:, self._setaxs + i])
            ax.set_xlabel(set_lbl)
            ax.set_ylabel(f'{p.label} ({p.unit})')
            self._paxs.append(ax)
            self._plines.append(ax.plot([], [])[0])

        self._laxs = []
        self._llines = []
        for i, (l, name, _) in enumerate(self._sr830s):
            ax0 = self._fig.add_subplot(grid[:-1, self._setaxs + len(self._params) + i])
            ax0.set_ylabel(f'{name} (V)')
            fmt = ScalarFormatter()
            fmt.set_powerlimits((-3, 3))
            ax0.get_yaxis().set_major_formatter(fmt)
            self._laxs.append(ax0)
            self._llines.append(ax0.plot([], [])[0])
            ax1 = self._fig.add_subplot(grid[-1, self._setaxs + len(self._params) + i], sharex=ax0)
            ax1.set_ylabel('Phase (°)')
            ax1.set_xlabel(set_lbl)
            self._laxs.append(ax1)
            self._llines.append(ax1.plot([], [])[0])
            plt.setp(ax0.get_xticklabels(), visible=False)
            
        self._fblaxs = []
        self._fbllines = []
        for i, l in enumerate(self._fbl_channels):
            ax0 = self._fig.add_subplot(grid[:-1, self._setaxs + len(self._params) + i + len(self._sr830s)])
            ax0.set_ylabel(f'FBL Channel {l} (V)')
            fmt = ScalarFormatter()
            fmt.set_powerlimits((-3, 3))
            ax0.get_yaxis().set_major_formatter(fmt)
            self._fblaxs.append(ax0)
            self._fbllines.append(ax0.plot([], [])[0])
            ax1 = self._fig.add_subplot(grid[-1, self._setaxs + len(self._params) + i + len(self._sr830s)], sharex=ax0)
            ax1.set_ylabel('Phase (°)')
            ax1.set_xlabel(set_lbl)
            self._fblaxs.append(ax1)
            self._fbllines.append(ax1.plot([], [])[0])
            plt.setp(ax0.get_xticklabels(), visible=False)

        self._fig.tight_layout()
        self._fig.show()

    def _update_1d_setax(self, setpoint, t):
        if self._setaxs == 0:
            return
        self._setaxline.set_xdata(np.append(self._setaxline.get_xdata(), t))
        self._setaxline.set_ydata(np.append(self._setaxline.get_ydata(), setpoint))
        self._setax.relim()
        self._setax.autoscale_view()

    def _update_1d_param(self, i, setpoint, value):
        self._plines[i].set_xdata(np.append(self._plines[i].get_xdata(), setpoint))
        self._plines[i].set_ydata(np.append(self._plines[i].get_ydata(), value))
        self._paxs[i].relim()
        self._paxs[i].autoscale_view()

    def _update_1d_sr830(self, i, setpoint, x, y):
        self._llines[i*2].set_xdata(np.append(self._llines[i*2].get_xdata(), setpoint))
        self._llines[i*2].set_ydata(np.append(self._llines[i*2].get_ydata(), x))
        self._llines[i*2+1].set_xdata(np.append(self._llines[i*2+1].get_xdata(), setpoint))
        self._llines[i*2+1].set_ydata(np.append(self._llines[i*2+1].get_ydata(), np.arctan2(y, x) * 180 / np.pi))
        self._laxs[i*2].relim()
        self._laxs[i*2].autoscale_view()
        self._laxs[i*2+1].relim()
        self._laxs[i*2+1].autoscale_view()
        
    def _update_1d_fbls(self, i, setpoint, r, theta):
        self._fbllines[i*2].set_xdata(np.append(self._fbllines[i*2].get_xdata(), setpoint))
        self._fbllines[i*2].set_ydata(np.append(self._fbllines[i*2].get_ydata(), r))
        self._fbllines[i*2+1].set_xdata(np.append(self._fbllines[i*2+1].get_xdata(), setpoint))
        self._fbllines[i*2+1].set_ydata(np.append(self._fbllines[i*2+1].get_ydata(), theta))
        self._fblaxs[i*2].relim()
        self._fblaxs[i*2].autoscale_view()
        self._fblaxs[i*2+1].relim()
        self._fblaxs[i*2+1].autoscale_view()

    def _redraw_1d_plot(self):
        self._fig.tight_layout()
        self._fig.canvas.draw()
        plt.pause(0.001)

    def _display_1d_plot(self):
        b = io.BytesIO()
        self._fig.savefig(b, format='png')
        display.display(display.Image(data=b.getbuffer(), format='png'))

    def sweep(self, set_param, vals, inter_delay=None):
        if inter_delay is not None:
            d = len(vals)*inter_delay
            h, m, s = int(d/3600), int(d/60) % 60, int(d) % 60
            print(f'Minimum duration: {h}h {m}m {s}s')

        self._prepare_1d_plots(set_param)
        try:
            meas = self._create_measurement(set_param)
            with meas.run() as datasaver:
                t0 = time.monotonic()
                for setpoint in vals:
                    t = time.monotonic() - t0
                    set_param.set(setpoint)
                    self._update_1d_setax(setpoint, t)

                    if inter_delay is not None:
                        plt.pause(inter_delay)

                    data = [
                        (set_param, setpoint),
                        ('time', t)
                    ]

                    if self._fbl is not None:
                        d = self._fbl.get_v_in(self._fbl_channels)
                        for i, (c, (r, theta)) in enumerate(zip(self._fbl_channels, d)):
                            data.extend([(f'fbl_c{c}_r', r), (f'fbl_c{c}_p', theta)])
                            self._update_1d_fbls(i, setpoint, r, theta)					
					
                    for i, (p, gain) in enumerate(self._params):
                        v = p.get()
                        v = v / gain
                        data.append((p, v))
                        self._update_1d_param(i, setpoint, v)

                    for i, (l, _, gain) in enumerate(self._sr830s):
                        _autorange_srs(l, 3)
                        x, y = l.snap('x', 'y')
                        x, y = x / gain, y / gain
                        data.extend([(l.X, x), (l.Y, y)])
                        self._update_1d_sr830(i, setpoint, x, y)

                    datasaver.add_result(*data)
                    
                    self._redraw_1d_plot()
        except KeyboardInterrupt:
            print('Interrupted.')

        d = time.monotonic() - t0
        h, m, s = int(d/3600), int(d/60) % 60, int(d) % 60
        print(f'Completed in: {h}h {m}m {s}s')

        self._display_1d_plot()
        plt.close(self._fig)

    def watch(self, max_duration=None, inter_delay=None):
        self._prepare_1d_plots()
        try:
            meas = self._create_measurement()
            with meas.run() as datasaver:
                t0 = time.monotonic()
                t = time.monotonic() - t0
                while max_duration is None or t < max_duration:
                    t = time.monotonic() - t0

                    if inter_delay is not None:
                        plt.pause(inter_delay)

                    data = [('time', t)]

                    for i, (p, gain) in enumerate(self._params):
                        v = p.get()
                        v = v / gain
                        data.append((p, v))
                        self._update_1d_param(i, t, v)

                    for i, (l, _, gain) in enumerate(self._sr830s):
                        _autorange_srs(l, 3)
                        x, y = l.snap('x', 'y')
                        x, y = x / gain, y / gain
                        data.extend([(l.X, x), (l.Y, y)])
                        self._update_1d_sr830(i, t, x, y)
                        
                    if self._fbl is not None:
                        d = self._fbl.get_v_in(self._fbl_channels)
                        for i, (c, (r, theta)) in enumerate(zip(self._fbl_channels, d)):
                            data.extend([(f'fbl_c{c}_r', r), (f'fbl_c{c}_p', theta)])
                            self._update_1d_fbls(i, t, r, theta)

                    datasaver.add_result(*data)
                    
                    self._redraw_1d_plot()
        except KeyboardInterrupt:
            print('Interrupted.')

        d = time.monotonic() - t0
        h, m, s = int(d/3600), int(d/60) % 60, int(d) % 60
        print(f'Completed in: {h}h {m}m {s}s')

        self._display_1d_plot()
        plt.close(self._fig)

    def megasweep(self, s_fast, v_fast, s_slow, v_slow, inter_delay=None):
        if inter_delay is not None:
            d = len(v_fast)*len(v_slow)*inter_delay
            h, m, s = int(d/3600), int(d/60) % 60, int(d) % 60
            print(f'Minimum duration: {h}h {m}m {s}s')

        t0 = time.monotonic()
        meas = self._create_measurement(s_fast, s_slow)
        try:
            with meas.run() as datasaver:
                for sp_slow in v_slow:
                    s_slow.set(sp_slow)

                    self._prepare_1d_plots(s_fast)
                    for sp_fast in v_fast:
                        t = time.monotonic() - t0
                        s_fast.set(sp_fast)
                        self._update_1d_setax(sp_fast, t)

                        if inter_delay is not None:
                            plt.pause(inter_delay)

                        data = [
                            (s_slow, sp_slow),
                            (s_fast, sp_fast),
                            ('time', t)
                        ]
                        for i, (p, gain) in enumerate(self._params):
                            v = p.get()
                            v = v / gain
                            data.append((p, v))
                            self._update_1d_param(i, sp_fast, v)

                        for i, (l, _, gain) in enumerate(self._sr830s):
                            _autorange_srs(l, 3)
                            x, y = l.snap('x', 'y')
                            x, y = x / gain, y / gain
                            data.extend([(l.X, x), (l.Y, y)])
                            self._update_1d_sr830(i, sp_fast, x, y)

                        datasaver.add_result(*data)
                        
                        self._redraw_1d_plot()
                    self._display_1d_plot()
                    plt.close(self._fig)
        except KeyboardInterrupt:
            print('Interrupted.')
            plt.close(self._fig)
        d = time.monotonic() - t0
        h, m, s = int(d/3600), int(d/60) % 60, int(d) % 60
        print(f'Completed in: {h}h {m}m {s}s')
		
		
def sweep1d(instr, start, end, step, delay, params):
    #example: sweep1D(Vg,0,1,0.1,0.5,[srs1,srs2,[FBL,0,1,2,10,11]])		
	s = Sweep()
    for p in params:
        if isinstance(p, SR830):
            s.follow_sr830(p,p.name)
        elif p is list and p[0].name ==' FBL':
            # need to do better in the future
            channels = p[1:]
            s.follow_fbl(channels)
        else:
            s.follow_param(p)
    s.sweep(instr, np.arange(start, end, step), inter_delay=delay)
    
