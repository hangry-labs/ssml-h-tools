# SSML-H Tools

`ssml-h-tools` is the reference Python parser, validator, and builder for
[SSML-H 1.0](https://hangrylabs.app/ns/ssml-h/1.0). It also supports a bounded
subset of standard W3C SSML 1.1.

The package is engine-neutral. It compiles markup into immutable synthesis
plans and leaves model inference, voice catalogs, profile storage, audio
assembly, and authorization to the integrating speech engine.

## Install

```bash
pip install ssml-h-tools
```

Python 3.10 or newer is required.

## Validate and compile

```python
from ssml_h import validate_ssml

plan = validate_ssml(
    """<speak version="1.1" xmlns="http://www.w3.org/2001/10/synthesis">
      Hello.<break time="250ms"/>Welcome back.
    </speak>""",
    "ssml",
)

for unit in plan.units:
    print(unit.kind, unit.text, unit.duration_ms)
```

Language and voice resolution are supplied by the host application:

```python
plan = validate_ssml(
    document,
    "ssml-h",
    default_language="en",
    resolve_language=my_language_resolver,
    validate_voice=my_voice_validator,
)
```

The parser rejects DTDs, entities, external references, unknown synthesis
namespaces, unsupported elements, and documents exceeding bounded resource
limits before model inference begins.

## Build documents

```python
from ssml_h import SSMLBuilder

document = SSMLBuilder.ssml_h(language="en-US")
document.define_voice(
    "Bob",
    gender="male",
    age="elderly",
    accent="american",
    seed=4242,
    sample="My name is Bob.",
    sample_language="en-US",
)

with document.voice("Bob") as bob:
    bob.text("Are we ready?")
with document.voice("Bob", direction="Calm and reassuring") as bob:
    bob.text("Everything is under control.")
document.break_(milliseconds=300)
with document.prosody(rate="slow") as slower:
    slower.text("Everything is prepared.")

xml = document.build()
plan = document.validate(allow_turn_direction=True)
```

XML is built with `ElementTree`; text and attributes are escaped rather than
concatenated. `scope="profile"` must be requested explicitly when defining a
persistent voice.

Per-turn natural-language direction is an optional processor capability. The
parser rejects `h:direction` unless the host explicitly passes
`allow_turn_direction=True`; compiled speech units then expose the normalized
instruction as `unit.direction`. The builder emits the namespaced attribute
through `voice(..., direction="...")` for named voices or
`sentence(direction="...")` for the default voice, only in SSML-H documents.

## Processor adapters

`<phoneme>` is disabled unless the host supplies a `render_phoneme` callback.
This prevents the core package from claiming an alphabet that the active model
cannot render. The callback receives `(alphabet, ph, source_text, language)`
and returns the text representation expected by the engine.

The host remains responsible for:

- mapping BCP 47 tags to model languages;
- validating saved or built-in voice names;
- advertising its actual capabilities;
- creating and cleaning request-scoped voices;
- atomically publishing persistent profiles; and
- executing advertised per-turn directions without speaking or persisting the
  instruction; and
- enforcing model, queue, duration, and output limits.

## Development

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python -m unittest discover -s tests -v
python -m build
python -m twine check dist/*
```

On Windows, use `.venv\Scripts\python.exe`.

## Release

Releases are published from GitHub Releases through PyPI Trusted Publishing.
No long-lived PyPI token is stored in GitHub. See the
[publishing guide](https://github.com/hangry-labs/ssml-h-tools/blob/main/docs/PUBLISHING.md).

## License

The tools are licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). The SSML-H
specification is maintained separately in
[`hangry-labs/ssml-h-spec`](https://github.com/hangry-labs/ssml-h-spec).
