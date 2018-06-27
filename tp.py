import time
import qcodes as qc


class TimeParameter(qc.Parameter):
    """
    A simple parameter that returns the current epoch time.
    """
    def __init__(self, name='time'):
        super().__init__(name, unit='s', label='Time', docstring='time in seconds')
        self._t0 = time.time()
        
    def get_raw(self):
        return time.time() - self._t0
    
    def set_raw(self, val):
        None


def loop_continuous(duration, inter_delay):
    """
    Loop for up to duration (seconds) with given inter_delay (seconds).
    """
    return qc.Loop(TimeParameter().sweep(0, duration, inter_delay), delay=inter_delay)
