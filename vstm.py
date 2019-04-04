# Stick this in a jupyter notebook cell.
import time
from qcodes import VisaInstrument

magnet = VisaInstrument('magnet1', 'ASRL11::INSTR')
magnet.set_terminator('\r\n')
magnet.ask('FIELD:MAG?')
def heater_on(mag):
    mag.write('PS 1')
    time.sleep(60)

def heater_off(mag):
    mag.write('PS 0')
    time.sleep(60)

def set_b(mag, b):
    mag.write(f'CONF:FIELD:PROG {b}')
    mag.write('RAMP')
    time.sleep(1)
    while int(mag.ask('STATE?')) == 1:
        time.sleep(0.5)

def get_b(mag):
    return float(mag.ask('FIELD:MAG?'))

mag = qc.Parameter('mag', unit='T', get_cmd=lambda: get_b(magnet), set_cmd=lambda b: set_b(magnet, b))
