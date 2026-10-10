# Processor Integration

`ssml-h-tools` owns XML parsing, structural validation, standard control
compilation, dynamic voice declarations, and immutable synthesis plans. A host
speech processor owns everything that depends on a model or deployment.

## Compile boundary

```python
from ssml_h import validate_ssml

plan = validate_ssml(
    source,
    input_type,
    default_language=request_language,
    default_voice=request_voice,
    resolve_language=resolve_language,
    validate_voice=validate_voice,
    render_phoneme=render_phoneme,
    allow_turn_direction=model_supports_turn_direction,
)
```

Callbacks must be deterministic and side-effect free. Compilation must finish
before model inference, temporary voice creation, or persistent writes begin.

### Language resolver

`resolve_language(tag)` receives an SSML `xml:lang` value and returns the
processor's canonical language id. Raise `ValueError` for unsupported tags.

### Voice validator

`validate_voice(name, document_voice_names)` verifies native and saved voice
names. Document-local dynamic definitions are already known to the compiler.
Raise `ValueError` when a referenced voice is unavailable or ambiguous.

### Phoneme renderer

`render_phoneme(alphabet, ph, source_text, language)` maps a supported phoneme
alphabet to the text representation expected by the model. Omit the callback
to reject `<phoneme>` completely. Never accept an alphabet merely because the
XML syntax is valid.

### Turn direction

Set `allow_turn_direction=True` only when the active processor can execute a
bounded natural-language delivery instruction. Each affected speech unit then
carries `unit.direction`. The host must preserve the resolved voice, must not
speak or persist the instruction, and must reject model conditioning
combinations it cannot honor. The attribute is valid on `<voice>` and `<s>`;
the latter directs the host's default voice binding. A nested `<voice>` has no
direction unless it declares its own namespaced `h:direction` attribute.

## Execution boundary

Execute `plan.units` in order. A `speech` unit carries text, language, voice,
composed prosody, and optional per-turn direction. A `break` unit carries
bounded silence in milliseconds.
Apply model-specific ranges before inference and reject values the processor
cannot honor.

Dynamic `plan.voice_definitions` require a request transaction:

1. Validate descriptors and profile collisions.
2. Create request-owned temporary references.
3. Reuse those references for matching speech units.
4. Synthesize and encode the complete response.
5. Publish `scope="profile"` definitions atomically only after success.
6. Clean temporary and uncommitted resources on success, failure, cancellation,
   or client disconnect.

Streaming and complete-response routes must share the same plan and cleanup
rules. A streaming disconnect is not a successful profile transaction.

## Capability reporting

Start with `ssml_capabilities()` and narrow the result to what the active
processor can execute. Supply only configured phoneme alphabets and set
`description_supported=False` when the model cannot consume free-form voice
descriptions. Set `turn_direction_supported=True` only when the execution
adapter consumes `unit.direction`. Add model-specific descriptor values and
operational limits in the host API rather than the portable package.
