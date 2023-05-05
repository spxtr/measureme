# MeasureMe

This is what I use to orchestrate measurements. It builds on Python 3, Jupyter
lab, Matplotlib, and QCoDeS.

## Installation

Installing python projects can be a real pain. Here is how I personally set up
lab computers to use measureme, but other ways can work fine. I do not like to
use tools such as Conda or pipenv, because I find them to be a real headache.

1. On Windows computers I typically use
[GitHub Desktop](https://desktop.github.com/) for git.
1. I install the latest Python 3 from python.org, system wide. I make sure that
I can run Python from the command line. On Windows this sometimes means running
`py` or `py3` or `python3`. I feel like it changes every time I do it, so just
try them all and see what sticks. Later versions of Windows will annoyingly
pop up some app store if you don't use the right incantation. Ignore that
nonsense.
1. Next, make sure `pip` exists with `python -m ensurepip`. Again, `pip` might
have some odd path like `pip3`.
1. `pip install jupyterlab`.
1. Install `qcodes` according to [their guide](https://qcodes.github.io/Qcodes/start/index.html#installing-qcodes-from-github).
First, `git clone` it, then `pip install -e /path/to/qcodes`. The `-e` means
you can update the installation by simply doing `git pull`.
1. Also install qcodes contrib drivers, if you use those instruments.
1. Test qcodes by controlling some instrument. You will likely need NI drivers.
1. Download and install measureme. Git clone, then `pip install -e` as you did
for qcodes.
1. Test measureme by following the basic usage section below!

## Basic usage

Import sweep and then set the `basedir`, which is the directory into which all
sweep data will be saved. The first measurement will be under `<basedir>/0`,
then `<basedir>/1`, and so on counting up. Organization above this level is
left entirely up to you.

```python
import sweep
sweep.set_basedir('/path/to/data/directory')
```

Configure QCoDeS instruments as you desire. For this document, I will use
dummy instruments, one representing a DAC that sets two gate voltages, and one
representing a DMM with DC and gate currents.

```python
from qcodes.tests.instrument_mocks import DummyInstrument
dac = DummyInstrument(name="dac", gates=['ch1', 'ch2'])
dmm = DummyInstrument(name="dmm", gates=['idc', 'ig'])
```

Now we can create a `Station` object and tell it to measure the two parameters
on the DMM. The station automatically follows time in addition to what you
specify.

```python
s = sweep.Station()
s.follow_param(dmm.idc)
s.follow_param(dmm.ig)
```

There is an optional gain parameter that will be divided out of all
measurements, so if `dmm.ig` is passing through a 100x amplifier, use
`s.follow_param(dmm.ig, gain=100)`.

We can take a single measurement (a 0D sweep) with `s.measure()`.

```python
result = s.measure()
```

This will print out the location that the data is saved in, but you can access
it programmatically from `result.datapath`. The data is stored as a compressed
TSV, which can be natively read by `numpy` with either `np.loadtxt` or
`np.genfromtxt`. The column names are stored in `result.metadata['columns']`,
and the metadata dictionary is also saved in JSON format in the same folder as
the data.

```python
print(result.metadata['columns'])
print(np.loadtxt(result.datapath))
```

If you wish to measure repeatedly over time, use `s.watch`. You'll want to pass
in a delay between measurements as well as a maximum duration (no limit if not
specified). Press the stop button in Jupyter (or hit ctrl-c in a terminal) to
interrupt the watch. All times are in seconds.

```python
result = s.watch(delay=1, max_duration=3600)
```

A 1D sweep is slightly more complicated. You'll need to call `s.sweep` with
the parameter to be swept, a list of setpoints, and an optional delay per
point.

```python
result = s.sweep(dac.ch1, [0, 0.1, 0.2, 0.3], delay=1)
```

This will set `dac.ch1` to 0, wait 1 second, then measure the DMM parameters,
then set `dac.ch1` to 0.1, wait 1 second, etc. As with a 0D sweep, the `result`
struct contains all the information you need in order to load up the data. In
practice, it is much more convenient to use `numpy` to generate the list of
setpoints. In this case, `np.linspace(0, 0.3, 4)` would do the trick.

A 2D sweep requires a slow parameter with setpoints and a fast parameter with
setpoints.

```python
result = s.sweep(
    dac.ch1, np.linspace(0, 1, 11),
    dac.ch2, np.linspace(0, 1, 11),
    slow_delay=10, fast_delay=1)
```

This will set `dac.ch1` to 0, wait 10 seconds, then sweep `dac.ch2` from 0 to 1,
waiting 1 second in between each, then to the next `dac.ch1` setpoint, wait 10
second, and so on. In this case, `dac.ch1` is the "slow" parameter and `dac.ch2`
is the "fast" parameter.

## Previous measurement information

To list previous measurements in a table along with metadata, use

```python
sweep.list_measurements()
```

To show information about a single measurement, replace 42 with the ID in

```python
sweep.measurement_info(42)
```

## Plotting

Call `s.plot(x, y, z)` to add a live plot. Note that `z` is optional, leaving it
off will result in a 1D plot.

```python
s.plot(dac.ch1, dmm.ig)

result = s.sweep(dac.ch1, np.linspace(0, 1, 11), delay=1)
```

When the sweep runs, a window will open up and the plot will update as data
comes in. You can plot multiple traces on a 1D plot by including them in the
same `plot` call.

```python
s.plot(dac.ch1, [dmm.ig, dmm.idc])
```

2D plots also work. **Warning**: I have found that 2D plots can really slow
down python, even though I tried to use multiprocessing to make this not the
case. I'll try to fix it sometime, but maybe don't use it for now?

```python
s.plot(dac.ch1, dac.ch2, dmm.idc)

result = s.sweep(
    dac.ch1, np.linspace(0, 1, 11),
    dac.ch2, np.linspace(0, 1, 11))
```
