from qcodes import VisaInstrument

class Yokogawa_7651(VisaInstrument):
    def __init__(self, name, address, **kwargs):
        super().__init__(name, address, terminator='\r\n', **kwargs)

        self.add_parameter('volt', unit='V', set_cmd='S{:f}\r\nE')
        self.connect_message()

    def output_on(self):
        self.write('O1')
        self.write('E')

    def output_off(self):
        self.write('O0')
        self.write('E')
