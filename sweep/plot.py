import multiprocessing


class Plotter:
    def __init__(self):
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
        self._plots.append((to_names(x), to_names(y), to_names(z)))

    def start(self):
        if len(self._plots) == 0:
            return
