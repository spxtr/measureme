from time import sleep
from qcodes import VisaInstrument, InstrumentChannel, ChannelList
from qcodes.utils.validators import Enum


class SensorChannel(InstrumentChannel):
    _CHANNEL_VAL = Enum('A', 'B')
    def __init__(self, parent, name, channel):
        super().__init__(parent, name)

        self._CHANNEL_VAL.validate(channel)
        self._channel = channel
        self._loop = 1 if channel == 'A' else 2

        self.add_parameter('temperature', get_cmd='INPUT {}:TEMP?'.format(self._channel),
                           get_parser=float,
                           label='Temerature',
                           unit='K')

class Cryocon_32B(VisaInstrument):
    def __init__(self, name, address, **kwargs):
        super().__init__(name, address, **kwargs)
        channels = ChannelList(self, "TempSensors", SensorChannel, snapshotable=False)
        for chan_name in ('A', 'B'):
            channel = SensorChannel(self, chan_name, chan_name)
            channels.append(channel)
            self.add_submodule(chan_name, channel)
        channels.lock()
        self.add_submodule("channels", channels)
        self.connect_message()
        
        # Enable overtemp protection.
        self.write('OVER:SOUR A')
        self.write('OVER:TEMP 310')
        self.write('OVER:ENAB ON')
    
    def stop(self):
        self.write('STOP')
        
    def control_on(self):
        self.write('CONTROL ON')
        
    def set_t(self, TA, TB):
        self.write('LOOP 1:SOURCE A')
        self.write('LOOP 2:SOURCE B')
        
        self.write('LOOP 1:TABLEIX 1')
        self.write('LOOP 2:TABLEIX 1')
        
        currT = self.A.temperature()
        maxT = max(currT, TA)
        if maxT < 8:
            self.write('LOOP 1:RANGE LOW')
        elif maxT < 70:
            self.write('LOOP 1:RANGE MID')
        else:
            self.write('LOOP 1:RANGE HI')
            
        self.write('LOOP 1:TYPE PID')
        self.write('LOOP 1:PGAIN 0.2')
        self.write('LOOP 1:IGAIN 0')
        self.write('LOOP 1:DGAIN 0')
        
        self.write('LOOP 2:TYPE PID')
        self.write('LOOP 2:PGAIN 0.1')
        self.write('LOOP 2:IGAIN 0')
        self.write('LOOP 2:DGAIN 0')
        
        self.write('LOOP 1:SETPT {}'.format(TA))
        self.write('LOOP 2:SETPT {}'.format(TB))
        
        self.control_on()
        
        self.write('INPUT A:RESET')
        self.write('INPUT B:RESET')
        
        
     def set_t_keep_PID(self, TA, TB):
        self.write('LOOP 1:SOURCE A')
        self.write('LOOP 2:SOURCE B')
        
        self.write('LOOP 1:TABLEIX 1')
        self.write('LOOP 2:TABLEIX 1')
        
        currT = self.A.temperature()
        maxT = max(currT, TA)
        if maxT < 8:
            self.write('LOOP 1:RANGE LOW')
        elif maxT < 70:
            self.write('LOOP 1:RANGE MID')
        else:
            self.write('LOOP 1:RANGE HI')
        
        self.write('LOOP 1:SETPT {}'.format(TA))
        self.write('LOOP 2:SETPT {}'.format(TB))
        
        self.control_on()
        
        self.write('INPUT A:RESET')
        self.write('INPUT B:RESET')