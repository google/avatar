# Avatar

Avatar aims to provide a scalable multi-platform Bluetooth testing tool capable
of running any Bluetooth test cases virtually and physically. It aims to
complete PTS-bot in the Pandora testing suite.

## Install

```bash
python -m venv venv
source venv/bin/activate.fish # or any other shell
pip install [-e] .
```

## Usage

```bash
python examples/example.py -c examples/simulated_bumble_android.yml --verbose
```

## Development

1. Make sure to have a `root-canal` instance running somewhere.
```bash
root-canal
```

1. Run the example using Bumble vs Bumble config file. The default `6402` HCI port of `root-canal` may be changed in this config file.
```
python examples/example.py -c examples/simulated_bumble_bumble.yml --verbose
```

3. Lint with `pyright` and `mypy`
```
pyright
mypy
```

3. Format & imports style
```
black avatar/ examples/
isort avatar/ examples/
```
