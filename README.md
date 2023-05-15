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
python cases/host_test.py -c cases/config.yml --verbose
```

## Development

1. Make sure to have a `root-canal` instance running somewhere.
```bash
root-canal
```

1. Run the example using Bumble vs Bumble config file. The default `6402` HCI port of `root-canal` may be changed in this config file.
```
python cases/host_test.py -c cases/config.yml --verbose
```

3. Lint with `pyright` and `mypy`
```
pyright
mypy
```

3. Format & imports style
```
black avatar/ cases/
isort avatar/ cases/
```
