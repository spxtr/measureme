import enum
import io
import math
import multiprocessing
import signal

import numpy as np
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
                if x not in point or y not in point:
                    continue
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
        self._plots.append((to_names(x), to_names(y), to_names(z)))

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
