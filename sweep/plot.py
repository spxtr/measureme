import enum
import io
import math
import multiprocessing
import signal

import numpy as np
import scipy
from scipy.interpolate import griddata
import matplotlib
matplotlib.use('Qt5Agg')
import matplotlib.pyplot as plt


class _Action(enum.Enum):
    START = 'start'
    STOP  = 'stop'
    SEND_IMAGE = 'send_image'
    ADD_POINT = 'add_point'


class _PlotProc:
    def __init__(self):
        pass
    
    def start(self, plots):
        self._plots = plots
        rows = math.ceil(len(plots) / 4)
        cols = len(plots) % 4 if len(plots) < 4 else 4
        self._fig = plt.figure(figsize=(4 * cols, 4 * rows))
        grid = plt.GridSpec(rows, cols)
        self._lines = []
        self._meshes = []
        self._axs = []
        for i, (xs, ys, zs) in enumerate(plots):
            ax = self._fig.add_subplot(grid[i // 4, i % 4])
            self._axs.append(ax)
            if len(ys) > 1 or len(xs) > 1:
                ax.legend()
            if len(xs) == 1:
                ax.set_xlabel(xs[0])
            if len(ys) == 1:
                ax.set_ylabel(ys[0])
            if len(zs) == 0:
                if len(xs) == 1:
                    for y in ys:
                        self._lines.append((xs[0], y, ax.plot([], [], label=y)[0]))
                else:
                    for x, y in zip(xs, ys):
                        self._lines.append((x, y, ax.plot([], [], label=f'{x} - {y}')[0]))
            else:
                self._meshes.append((xs[0], ys[0], zs[0], [], [], [], ax))
        self._fig.show()
    
    def stop(self):
        plt.close(self._fig)
    
    def add_points(self, points):
        for point in points:
            for x, y, line in self._lines:
                if x not in point or y not in point:
                    continue
                line.set_xdata(np.append(line.get_xdata(), point[x]))
                line.set_ydata(np.append(line.get_ydata(), point[y]))
            for x, y, z, xd, yd, zd, ax in self._meshes:
                if x not in point or y not in point or z not in point:
                    continue
                xd.append(point[x])
                yd.append(point[y])
                zd.append(point[z])
                xmin, xmax, lx = np.min(xd), np.max(xd), len(np.unique(xd))
                ymin, ymax, ly = np.min(yd), np.max(yd), len(np.unique(yd))
                xi = np.linspace(xmin, xmax, lx)
                yi = np.linspace(ymin, ymax, ly)
                X, Y = np.meshgrid(xi, yi)
                ax.clear()
                if lx > 1 and ly > 1:
                    zi = griddata((xd, yd), zd, (X, Y))
                    ax.pcolormesh(X, Y, zi, shading='nearest')
                    ax.set_xlabel(x)
                    ax.set_ylabel(y)
                elif lx == 1 and ly > 1:
                    ax.plot(yd, zd)
                    ax.set_xlabel(y)
                    ax.set_ylabel(z)
                elif ly == 1 and lx > 1:
                    ax.plot(xd, zd)
                    ax.set_xlabel(x)
                    ax.set_ylabel(z)
                if lx > 1 and ly > 1:
                    ax.set_xlim(np.min(xd), np.max(xd))
                    ax.set_ylim(np.min(yd), np.max(yd))
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
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    p = _PlotProc()
    quit = False
    while not quit:
        messages = []
        while conn.poll():
            messages.append(conn.recv())
        data = []
        send = False
        for m in messages:
            if m['action'] == _Action.START:
                p.start(m['plots'])
            elif m['action'] == _Action.STOP:
                quit = True
            elif m['action'] == _Action.SEND_IMAGE:
                send = True
            elif m['action'] == _Action.ADD_POINT:
                data.append(m['data'])
        if len(data) > 0:
            p.add_points(data)
        if send:
            conn.send(p.image())
        if quit:
            p.stop()
        plt.pause(0.001)

class Plotter:
    def __init__(self):
        self._plots = []
        self._proc = None
        self._parent_pipe = None

    def reset_plots(self):
        self._plots = []

    def plot(self, x, y, z):
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
        xs, ys, zs = to_names(x), to_names(y), to_names(z)
        if len(xs) > 1 and len(ys) > 1 and len(xs) != len(ys):
            raise ValueError('if multiple xs given, number must be same as ys')
        if len(zs) == 1 and (len(xs) > 1 or len(ys) > 1):
            raise ValueError('2d plots can only have one x and y')
        if len(zs) > 1:
            raise ValueError('can only have one z parameter')
        self._plots.append((xs, ys, zs))

    def set_cols(self, cols):
        self._cols = cols

    def _format_data_map(self, data):
        m = {}
        for k, v in zip(self._cols, data):
            m[k] = v
        return m

    def __enter__(self):
        if len(self._plots) == 0: return self
        ctx = multiprocessing.get_context('spawn')
        self._parent_pipe, child_pipe = ctx.Pipe()
        self._proc = ctx.Process(target=_plot_loop, args=(child_pipe,), daemon=True)
        self._proc.start()
        self._parent_pipe.send({
            'action': _Action.START,
            'plots': self._plots,
        })
        return self

    def __exit__(self, type, value, traceback):
        if len(self._plots) == 0:
            return
        self._parent_pipe.send({'action': _Action.STOP})
        self._proc.join()

    def add_point(self, data):
        if len(self._plots) == 0: return
        self._parent_pipe.send({
            'action': _Action.ADD_POINT,
            'data': self._format_data_map(data),
        })

    def send_image(self):
        if len(self._plots) == 0: return None
        self._parent_pipe.send({'action': _Action.SEND_IMAGE})
        return self._parent_pipe.recv().getbuffer()
