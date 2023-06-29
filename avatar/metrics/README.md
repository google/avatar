# Metrics

Avatar metrics use `perfetto` traces.

## Perfetto traces

For convenience, `trace_pb2.py` and `trace_pb2.pyi` are pre-generated.

To regenerate them run the following:

```
pip install protoc-exe
protoc trace.proto --pyi_out=./ --python_out=./
```

To ensure compliance with the linter, you must modify the generated
`.pyi` file by replacing `Union[T, _Mapping]` to `T`.
