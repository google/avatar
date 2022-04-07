# Blueberry DUT-to-reference tests

## Install

```bash
python3 -m venv venv
. venv/bin/activate.fish # or any other shell
pip install -e .[development]
```

## Build gRPC test interfaces

```bash
inv build-grpc
```

## Usage

```bash
python3 examples/example.py --address ADDRESS
```
