# Pandora DUT-to-reference tests

## Install

```bash
git submodule update --init
python -m venv venv
source venv/bin/activate.fish # or any other shell
pip install [-e] bt-test-interfaces/python
pip install [-e] .
```

## Rebuild gRPC Bluetooth test interfaces

```bash
pip install grpcio-tools==1.46.3
./bt-test-interfaces/python/_build/grpc.py
```

## Usage

```bash
python examples/example.py -c examples/example_config.yml
```
