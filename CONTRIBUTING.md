# Contributing

Changes should preserve the boundary between portable markup handling and
speech-engine behavior. Model loading, inference, profile persistence, and
audio processing belong in processor adapters, not this package.

Before opening a pull request, run:

```bash
python -m unittest discover -s tests -v
python -m build
python -m twine check dist/*
```

Specification changes should be proposed in
[`hangry-labs/ssml-h-spec`](https://github.com/hangry-labs/ssml-h-spec) first.
