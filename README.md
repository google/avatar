# Avatar

Avatar is a python Bluetooth testing tool orchestrating multiple devices which
implement the [Pandora interfaces](
https://github.com/google/bt-test-interfaces).

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

## Specify a test bed
```bash
python cases/host_test.py -c cases/config.yml --test_bed bumble.bumbles --verbose
```

## Development

1. Make sure to have a `root-canal` instance running somewhere.
   ```bash
   root-canal
   ```

1. Run the example using Bumble vs Bumble config file. The default `6402` HCI
   port of `root-canal` may be changed in this config file.
   ```
   python cases/host_test.py -c cases/config.yml --verbose
   ```

1. Lint with `pyright` and `mypy`
   ```
   pyright
   mypy
   ```

1. Format & imports style
   ```
   black avatar/ cases/
   isort avatar/ cases/
   ```
