from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden

SSML_NAMESPACE = "http://www.w3.org/2001/10/synthesis"
SSML_H_NAMESPACE = "https://hangrylabs.app/ns/ssml-h/1.0"
XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
XML_LANGUAGE_ATTRIBUTE = f"{{{XML_NAMESPACE}}}lang"
XML_DIRECTION_ATTRIBUTE = f"{{{SSML_H_NAMESPACE}}}direction"

MAX_SSML_SOURCE_CHARACTERS = 50_000
MAX_SSML_ELEMENTS = 300
MAX_SSML_NESTING = 12
MAX_SSML_UNITS = 200
MAX_SSML_VOICE_DEFINITIONS = 12
MAX_BREAK_MS = 10_000
MAX_TOTAL_BREAK_MS = 60_000
MAX_VOICE_SAMPLE_CHARACTERS = 500
MAX_VOICE_DESCRIPTION_CHARACTERS = 500
MAX_PHONEME_CHARACTERS = 300
MAX_TURN_DIRECTION_CHARACTERS = 240

VOICE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
BREAK_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)(ms|s)$", re.IGNORECASE)
PERCENT_PATTERN = re.compile(r"^([+-]?\d+(?:\.\d+)?)%$")
SEMITONE_PATTERN = re.compile(r"^([+-]?\d+(?:\.\d+)?)st$", re.IGNORECASE)
DECIBEL_PATTERN = re.compile(r"^([+-]?\d+(?:\.\d+)?)dB$", re.IGNORECASE)

VOICE_DEFINITION_ATTRIBUTES = {
    "name",
    "scope",
    "replace",
    "seed",
    "gender",
    "age",
    "pitch",
    "style",
    "languages",
    "accent",
    "dialect",
}
VOICE_DESIGN_ATTRIBUTES = {
    "gender",
    "age",
    "pitch",
    "style",
    "languages",
    "accent",
    "dialect",
}

RATE_NAMES = {
    "x-slow": 0.5,
    "slow": 0.75,
    "medium": 1.0,
    "default": 1.0,
    "fast": 1.25,
    "x-fast": 1.5,
}
PITCH_NAMES = {
    "x-low": -4.0,
    "low": -2.0,
    "medium": 0.0,
    "default": 0.0,
    "high": 2.0,
    "x-high": 4.0,
}
VOLUME_NAMES = {
    "silent": 0.0,
    "x-soft": 0.4,
    "soft": 0.7,
    "medium": 1.0,
    "default": 1.0,
    "loud": 1.3,
    "x-loud": 1.6,
}
BREAK_STRENGTHS = {
    "none": 0,
    "x-weak": 100,
    "weak": 200,
    "medium": 350,
    "strong": 600,
    "x-strong": 900,
}


class SSMLValidationError(ValueError):
    """Raised when an SSML or SSML-H document is invalid or unsupported."""


LanguageResolver = Callable[[str], str]
VoiceValidator = Callable[[str, frozenset[str]], None]
PhonemeRenderer = Callable[[str, str, str, str | None], str]


@dataclass(frozen=True)
class SSMLProsody:
    rate: float = 1.0
    pitch_semitones: float = 0.0
    volume: float = 1.0

    @property
    def is_neutral(self) -> bool:
        return self == SSMLProsody()


@dataclass(frozen=True)
class SSMLVoiceDefinition:
    name: str
    scope: Literal["request", "profile"] = "request"
    replace: bool = False
    seed: int | None = None
    gender: str | None = None
    age: str | None = None
    pitch: str | None = None
    style: str | None = None
    languages: tuple[str, ...] = ()
    accent: str | None = None
    dialect: str | None = None
    description: str | None = None
    sample: str | None = None
    sample_language: str | None = None


@dataclass(frozen=True)
class SSMLUnit:
    kind: Literal["speech", "break"]
    text: str = ""
    duration_ms: int = 0
    language: str | None = None
    language_explicit: bool = False
    voice: str | None = None
    prosody: SSMLProsody = field(default_factory=SSMLProsody)
    direction: str | None = None


@dataclass(frozen=True)
class SSMLPlan:
    input_type: Literal["ssml", "ssml-h"]
    units: tuple[SSMLUnit, ...]
    voice_definitions: tuple[SSMLVoiceDefinition, ...] = ()

    @property
    def voices(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(unit.voice for unit in self.units if unit.voice))

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(unit.language for unit in self.units if unit.language))


@dataclass(frozen=True)
class _Context:
    language: str | None
    language_explicit: bool
    voice: str | None
    prosody: SSMLProsody = field(default_factory=SSMLProsody)
    direction: str | None = None


def _qualified_name(value: str) -> tuple[str, str]:
    if value.startswith("{"):
        namespace, local = value[1:].split("}", 1)
        return namespace, local
    return "", value


def _local_attributes(element) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for name, value in element.attrib.items():
        namespace, local = _qualified_name(name)
        if namespace and namespace != XML_NAMESPACE:
            raise SSMLValidationError(f"Unsupported namespaced attribute '{name}'.")
        attributes[name if namespace == XML_NAMESPACE else local] = value
    return attributes


def _require_attributes(element, allowed: set[str]) -> dict[str, str]:
    attributes = _local_attributes(element)
    unknown = sorted(set(attributes) - allowed)
    if unknown:
        namespace, local = _qualified_name(element.tag)
        del namespace
        raise SSMLValidationError(f"Unsupported attribute(s) on <{local}>: {', '.join(unknown)}.")
    return attributes


def _voice_attributes(
    element,
    input_type: Literal["ssml", "ssml-h"],
    allow_turn_direction: bool,
) -> tuple[dict[str, str], str | None]:
    direction: str | None = None
    standard_attributes: dict[str, str] = {}
    for name, value in element.attrib.items():
        namespace, local = _qualified_name(name)
        if name == XML_DIRECTION_ATTRIBUTE:
            if input_type != "ssml-h":
                raise SSMLValidationError("h:direction requires input_type='ssml-h'.")
            if not allow_turn_direction:
                raise SSMLValidationError(
                    "SSML-H h:direction is not enabled by this processor profile."
                )
            direction = " ".join(value.split()).strip()
            if not direction:
                raise SSMLValidationError("SSML-H h:direction must not be empty.")
            if len(direction) > MAX_TURN_DIRECTION_CHARACTERS:
                raise SSMLValidationError(
                    f"SSML-H h:direction is limited to {MAX_TURN_DIRECTION_CHARACTERS} characters."
                )
            continue
        if namespace:
            raise SSMLValidationError(f"Unsupported namespaced attribute '{name}'.")
        standard_attributes[local] = value
    unknown = sorted(set(standard_attributes) - {"name", "required"})
    if unknown:
        raise SSMLValidationError(f"Unsupported attribute(s) on <voice>: {', '.join(unknown)}.")
    return standard_attributes, direction


def _plain_text(element, element_name: str, limit: int | None = None) -> str:
    if list(element):
        raise SSMLValidationError(f"<{element_name}> does not allow nested elements.")
    value = " ".join((element.text or "").split()).strip()
    if limit is not None and len(value) > limit:
        raise SSMLValidationError(f"<{element_name}> is limited to {limit} characters.")
    return value


def _parse_bool(value: str, attribute: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise SSMLValidationError(f"SSML-H attribute '{attribute}' must be true or false.")


def _parse_seed(value: str) -> int:
    try:
        seed = int(value)
    except ValueError as exc:
        raise SSMLValidationError("SSML-H seed must be an unsigned 32-bit integer.") from exc
    if seed < 0 or seed > 2**32 - 1:
        raise SSMLValidationError("SSML-H seed must be between 0 and 4294967295.")
    return seed


def _parse_voice_definition(element) -> SSMLVoiceDefinition:
    attributes = _require_attributes(element, VOICE_DEFINITION_ATTRIBUTES)
    name = attributes.get("name", "").strip()
    if not VOICE_NAME_PATTERN.fullmatch(name):
        raise SSMLValidationError(
            "SSML-H voice names must start with a letter and contain at most 64 letters, numbers, dots, hyphens, or underscores."
        )
    scope = attributes.get("scope", "request").strip().lower()
    if scope not in {"request", "profile"}:
        raise SSMLValidationError("SSML-H voice scope must be 'request' or 'profile'.")
    replace = _parse_bool(attributes.get("replace", "false"), "replace")
    if replace and scope != "profile":
        raise SSMLValidationError("SSML-H replace=true is valid only with scope='profile'.")
    seed = _parse_seed(attributes["seed"]) if "seed" in attributes else None

    description = None
    sample = None
    sample_language = None
    seen_children: set[str] = set()
    for child in element:
        namespace, local = _qualified_name(child.tag)
        if namespace != SSML_H_NAMESPACE or local not in {"description", "sample"}:
            raise SSMLValidationError(f"Unsupported SSML-H voice-definition child <{local}>.")
        if local in seen_children:
            raise SSMLValidationError(
                f"SSML-H <{local}> may appear only once per voice definition."
            )
        seen_children.add(local)
        if local == "description":
            _require_attributes(child, set())
            description = _plain_text(child, "h:description", MAX_VOICE_DESCRIPTION_CHARACTERS)
            if not description:
                raise SSMLValidationError("SSML-H <h:description> must not be empty.")
        else:
            child_attributes = _require_attributes(child, {XML_LANGUAGE_ATTRIBUTE})
            sample = _plain_text(child, "h:sample", MAX_VOICE_SAMPLE_CHARACTERS)
            if not sample:
                raise SSMLValidationError("SSML-H <h:sample> must not be empty.")
            sample_language = child_attributes.get(XML_LANGUAGE_ATTRIBUTE, "").strip() or None
        if (child.tail or "").strip():
            raise SSMLValidationError(
                "SSML-H voice definitions cannot contain metadata text outside child elements."
            )

    design_values = {
        key: attributes.get(key, "").strip() or None for key in VOICE_DESIGN_ATTRIBUTES
    }
    languages = tuple(part for part in (design_values.pop("languages") or "").split() if part)
    if not any(design_values.values()) and not languages and not description:
        raise SSMLValidationError(
            f"SSML-H voice definition '{name}' requires at least one voice-design property or h:description."
        )
    return SSMLVoiceDefinition(
        name=name,
        scope=scope,
        replace=replace,
        seed=seed,
        languages=languages,
        description=description,
        sample=sample,
        sample_language=sample_language,
        **design_values,
    )


def _parse_metadata(root, input_type: Literal["ssml", "ssml-h"]) -> tuple[SSMLVoiceDefinition, ...]:
    definitions: list[SSMLVoiceDefinition] = []
    extension_seen = False
    for child in root:
        namespace, local = _qualified_name(child.tag)
        if namespace not in {"", SSML_NAMESPACE} or local != "metadata":
            continue
        _require_attributes(child, set())
        for metadata_child in child:
            child_namespace, child_local = _qualified_name(metadata_child.tag)
            if child_namespace != SSML_H_NAMESPACE or child_local != "extensions":
                raise SSMLValidationError(
                    f"Unsupported metadata element <{child_local}> in this SSML profile."
                )
            if input_type != "ssml-h":
                raise SSMLValidationError("SSML-H metadata requires input_type='ssml-h'.")
            if extension_seen:
                raise SSMLValidationError("SSML-H allows at most one <h:extensions> element.")
            extension_seen = True
            attributes = _require_attributes(metadata_child, {"version"})
            if attributes.get("version") != "1.0":
                raise SSMLValidationError("SSML-H <h:extensions> requires version='1.0'.")
            if (metadata_child.text or "").strip():
                raise SSMLValidationError("SSML-H <h:extensions> cannot contain text.")
            for definition_element in metadata_child:
                definition_namespace, definition_local = _qualified_name(definition_element.tag)
                if (
                    definition_namespace != SSML_H_NAMESPACE
                    or definition_local != "voice-definition"
                ):
                    raise SSMLValidationError(
                        f"Unsupported SSML-H extension element <{definition_local}>."
                    )
                definitions.append(_parse_voice_definition(definition_element))
                if (definition_element.tail or "").strip():
                    raise SSMLValidationError("SSML-H metadata cannot contain synthesis text.")
    if len(definitions) > MAX_SSML_VOICE_DEFINITIONS:
        raise SSMLValidationError(
            f"SSML-H is limited to {MAX_SSML_VOICE_DEFINITIONS} voice definitions per document."
        )
    names = [definition.name for definition in definitions]
    if len(set(names)) != len(names):
        raise SSMLValidationError("SSML-H voice definition names must be unique within a document.")
    return tuple(definitions)


def _parse_break_ms(attributes: dict[str, str]) -> int:
    if "time" in attributes and "strength" in attributes:
        raise SSMLValidationError("<break> accepts either time or strength, not both.")
    if "strength" in attributes:
        strength = attributes["strength"].strip().lower()
        if strength not in BREAK_STRENGTHS:
            raise SSMLValidationError(
                "<break> strength must be none, x-weak, weak, medium, strong, or x-strong."
            )
        return BREAK_STRENGTHS[strength]
    value = attributes.get("time", "").strip()
    match = BREAK_PATTERN.fullmatch(value)
    if not match:
        raise SSMLValidationError(
            "<break> requires time such as '500ms' or '1.5s', or a supported strength."
        )
    number = float(match.group(1))
    milliseconds = round(number * (1000 if match.group(2).lower() == "s" else 1))
    if milliseconds > MAX_BREAK_MS:
        raise SSMLValidationError(f"Each <break> is limited to {MAX_BREAK_MS / 1000:g} seconds.")
    return milliseconds


def _parse_rate(value: str) -> float:
    normalized = value.strip().lower()
    if normalized in RATE_NAMES:
        return RATE_NAMES[normalized]
    match = PERCENT_PATTERN.fullmatch(normalized)
    if not match:
        raise SSMLValidationError("<prosody rate> must be a supported name or percentage.")
    multiplier = float(match.group(1)) / 100
    if multiplier <= 0:
        raise SSMLValidationError("<prosody rate> must be greater than 0%.")
    return multiplier


def _parse_pitch(value: str) -> float:
    normalized = value.strip().lower()
    if normalized in PITCH_NAMES:
        return PITCH_NAMES[normalized]
    semitone_match = SEMITONE_PATTERN.fullmatch(normalized)
    if semitone_match:
        return float(semitone_match.group(1))
    percent_match = PERCENT_PATTERN.fullmatch(normalized)
    if percent_match:
        factor = 1 + float(percent_match.group(1)) / 100
        if factor <= 0:
            raise SSMLValidationError(
                "<prosody pitch> percentage must remain above zero frequency."
            )
        return 12 * math.log2(factor)
    raise SSMLValidationError(
        "<prosody pitch> must be a supported name, percentage, or semitone value such as '+2st'."
    )


def _parse_volume(value: str) -> float:
    normalized = value.strip().lower()
    if normalized in VOLUME_NAMES:
        return VOLUME_NAMES[normalized]
    decibel_match = DECIBEL_PATTERN.fullmatch(normalized)
    if decibel_match:
        return 10 ** (float(decibel_match.group(1)) / 20)
    raise SSMLValidationError(
        "<prosody volume> must be a supported name or decibel value such as '-3dB'."
    )


def _prosody_context(element, context: _Context) -> _Context:
    attributes = _require_attributes(element, {"rate", "pitch", "volume"})
    rate = context.prosody.rate * (
        _parse_rate(attributes["rate"]) if attributes.get("rate", "").strip() else 1
    )
    pitch = context.prosody.pitch_semitones + (
        _parse_pitch(attributes["pitch"]) if attributes.get("pitch", "").strip() else 0
    )
    volume = context.prosody.volume * (
        _parse_volume(attributes["volume"]) if attributes.get("volume", "").strip() else 1
    )
    if not 0.25 <= rate <= 4.0:
        raise SSMLValidationError("Composed SSML prosody rate must be between 0.25 and 4.0.")
    if not -24.0 <= pitch <= 24.0:
        raise SSMLValidationError("Composed SSML prosody pitch must be between -24st and +24st.")
    if not 0.0 <= volume <= 4.0:
        raise SSMLValidationError("Composed SSML prosody volume must be between 0 and 4.0.")
    return _Context(
        context.language,
        context.language_explicit,
        context.voice,
        SSMLProsody(rate, pitch, volume),
        context.direction,
    )


def _join_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    separator = ""
    if not left[-1].isspace() and not right[0].isspace() and right[0] not in ".,;:!?)]}":
        separator = " "
    return f"{left}{separator}{right}"


def _append_speech(units: list[SSMLUnit], text: str, context: _Context) -> None:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return
    if units and units[-1].kind == "speech":
        previous = units[-1]
        if (
            previous.language == context.language
            and previous.language_explicit == context.language_explicit
            and previous.voice == context.voice
            and previous.prosody == context.prosody
            and previous.direction == context.direction
        ):
            units[-1] = SSMLUnit(
                "speech",
                text=_join_text(previous.text, normalized),
                language=context.language,
                language_explicit=context.language_explicit,
                voice=context.voice,
                prosody=context.prosody,
                direction=context.direction,
            )
            return
    units.append(
        SSMLUnit(
            "speech",
            text=normalized,
            language=context.language,
            language_explicit=context.language_explicit,
            voice=context.voice,
            prosody=context.prosody,
            direction=context.direction,
        )
    )


def _ordinal(value: str) -> str:
    try:
        number = int(value)
    except ValueError as exc:
        raise SSMLValidationError("<say-as interpret-as='ordinal'> requires an integer.") from exc
    if len(value.lstrip("+-")) > 18:
        raise SSMLValidationError("Ordinal values are limited to 18 digits.")
    suffix = (
        "th"
        if 10 <= abs(number) % 100 <= 20
        else {1: "st", 2: "nd", 3: "rd"}.get(abs(number) % 10, "th")
    )
    return f"{number}{suffix}"


def _say_as(value: str, interpretation: str, language: str | None) -> str:
    mode = interpretation.strip().lower()
    if mode == "characters":
        return " ".join(value)
    if mode == "digits":
        if not value.isdigit():
            raise SSMLValidationError("<say-as interpret-as='digits'> requires digits only.")
        return " ".join(value)
    if mode == "cardinal":
        if not re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", value):
            raise SSMLValidationError("<say-as interpret-as='cardinal'> requires a number.")
        return value
    if mode == "ordinal":
        if (language or "").split("-", 1)[0].lower() != "en":
            raise SSMLValidationError("Ordinal say-as is currently supported for English only.")
        return _ordinal(value)
    raise SSMLValidationError(
        "Unsupported <say-as> interpretation. Supported values: characters, digits, cardinal, ordinal."
    )


def compile_ssml(
    document: str,
    input_type: Literal["ssml", "ssml-h"],
    *,
    default_language: str | None = None,
    default_voice: str | None = None,
    resolve_language: LanguageResolver | None = None,
    validate_voice: VoiceValidator | None = None,
    render_phoneme: PhonemeRenderer | None = None,
    allow_turn_direction: bool = False,
) -> SSMLPlan:
    if len(document) > MAX_SSML_SOURCE_CHARACTERS:
        raise SSMLValidationError(
            f"SSML source is limited to {MAX_SSML_SOURCE_CHARACTERS} characters."
        )
    if "<!DOCTYPE" in document.upper() or "<!ENTITY" in document.upper():
        raise SSMLValidationError(
            "Invalid or unsafe SSML: DTD and entity declarations are forbidden."
        )
    try:
        root = DefusedET.fromstring(
            document,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except (ParseError, DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden) as exc:
        raise SSMLValidationError(f"Invalid or unsafe SSML: {exc}.") from exc

    elements = list(root.iter())
    if len(elements) > MAX_SSML_ELEMENTS:
        raise SSMLValidationError(f"SSML is limited to {MAX_SSML_ELEMENTS} elements.")
    root_namespace, root_name = _qualified_name(root.tag)
    if root_name != "speak" or root_namespace not in {"", SSML_NAMESPACE}:
        raise SSMLValidationError("SSML requires one <speak> root in the W3C synthesis namespace.")
    root_attributes = _require_attributes(root, {"version", XML_LANGUAGE_ATTRIBUTE})
    version = root_attributes.get("version", "1.1" if input_type == "ssml-h" else "1.0")
    if version not in {"1.0", "1.1"}:
        raise SSMLValidationError("SSML <speak> version must be '1.0' or '1.1'.")
    if input_type == "ssml-h" and version != "1.1":
        raise SSMLValidationError("SSML-H 1.0 requires <speak version='1.1'>.")

    root_language = default_language
    root_language_explicit = False
    xml_language = root_attributes.get(XML_LANGUAGE_ATTRIBUTE, "").strip()
    if xml_language:
        if resolve_language is None:
            root_language = xml_language
        else:
            try:
                root_language = resolve_language(xml_language)
            except ValueError as exc:
                raise SSMLValidationError(str(exc)) from exc
        root_language_explicit = True

    definitions = _parse_metadata(root, input_type)
    definition_names = frozenset(definition.name for definition in definitions)
    units: list[SSMLUnit] = []
    total_break_ms = 0

    def walk(parent, context: _Context, depth: int) -> None:
        nonlocal total_break_ms
        if depth > MAX_SSML_NESTING:
            raise SSMLValidationError(f"SSML nesting is limited to {MAX_SSML_NESTING} levels.")
        _append_speech(units, parent.text or "", context)
        for element in parent:
            namespace, tag = _qualified_name(element.tag)
            if tag == "metadata" and namespace in {"", SSML_NAMESPACE}:
                if units or (element.tail or "").strip():
                    if units:
                        raise SSMLValidationError(
                            "<metadata> must appear before synthesis content."
                        )
                _append_speech(units, element.tail or "", context)
                continue
            if namespace not in {"", SSML_NAMESPACE}:
                raise SSMLValidationError(f"Unsupported synthesis namespace on <{tag}>.")
            if tag == "break":
                attributes = _require_attributes(element, {"time", "strength"})
                if list(element) or (element.text or "").strip():
                    raise SSMLValidationError("<break> must be empty.")
                duration_ms = _parse_break_ms(attributes)
                total_break_ms += duration_ms
                if total_break_ms > MAX_TOTAL_BREAK_MS:
                    raise SSMLValidationError(
                        f"Total SSML break time is limited to {MAX_TOTAL_BREAK_MS / 1000:g} seconds."
                    )
                units.append(
                    SSMLUnit(
                        "break",
                        duration_ms=duration_ms,
                        language=context.language,
                        language_explicit=context.language_explicit,
                        voice=context.voice,
                        prosody=context.prosody,
                        direction=context.direction,
                    )
                )
            elif tag == "voice":
                attributes, direction = _voice_attributes(
                    element,
                    input_type,
                    allow_turn_direction,
                )
                name = attributes.get("name", "").strip()
                if not name:
                    raise SSMLValidationError("<voice> requires a non-empty name attribute.")
                if attributes.get("required", "name").strip() not in {"", "name"}:
                    raise SSMLValidationError(
                        "This processor profile supports <voice required='name'> only."
                    )
                if name not in definition_names and validate_voice is not None:
                    try:
                        validate_voice(name, definition_names)
                    except ValueError as exc:
                        raise SSMLValidationError(str(exc)) from exc
                walk(
                    element,
                    _Context(
                        context.language,
                        context.language_explicit,
                        name,
                        context.prosody,
                        direction,
                    ),
                    depth + 1,
                )
            elif tag == "lang":
                attributes = _require_attributes(element, {XML_LANGUAGE_ATTRIBUTE})
                requested = attributes.get(XML_LANGUAGE_ATTRIBUTE, "").strip()
                if not requested:
                    raise SSMLValidationError("<lang> requires an xml:lang attribute.")
                try:
                    resolved = resolve_language(requested) if resolve_language else requested
                except ValueError as exc:
                    raise SSMLValidationError(str(exc)) from exc
                walk(
                    element,
                    _Context(resolved, True, context.voice, context.prosody, context.direction),
                    depth + 1,
                )
            elif tag == "prosody":
                walk(element, _prosody_context(element, context), depth + 1)
            elif tag in {"p", "s"}:
                _require_attributes(element, {XML_LANGUAGE_ATTRIBUTE})
                nested_context = context
                nested_language = element.attrib.get(XML_LANGUAGE_ATTRIBUTE, "").strip()
                if nested_language:
                    try:
                        resolved = (
                            resolve_language(nested_language)
                            if resolve_language
                            else nested_language
                        )
                    except ValueError as exc:
                        raise SSMLValidationError(str(exc)) from exc
                    nested_context = _Context(
                        resolved,
                        True,
                        context.voice,
                        context.prosody,
                        context.direction,
                    )
                walk(element, nested_context, depth + 1)
            elif tag in {"token", "w"}:
                _require_attributes(element, set())
                walk(element, context, depth + 1)
            elif tag == "sub":
                attributes = _require_attributes(element, {"alias"})
                _plain_text(element, "sub")
                alias = attributes.get("alias", "").strip()
                if not alias:
                    raise SSMLValidationError("<sub> requires a non-empty alias attribute.")
                _append_speech(units, alias, context)
            elif tag == "say-as":
                attributes = _require_attributes(element, {"interpret-as"})
                value = _plain_text(element, "say-as")
                if not value:
                    raise SSMLValidationError("<say-as> must contain text.")
                _append_speech(
                    units,
                    _say_as(value, attributes.get("interpret-as", ""), context.language),
                    context,
                )
            elif tag == "phoneme":
                attributes = _require_attributes(element, {"alphabet", "ph"})
                source_text = _plain_text(element, "phoneme")
                alphabet = attributes.get("alphabet", "").strip().lower()
                phonemes = " ".join(attributes.get("ph", "").split())
                if not alphabet or not phonemes:
                    raise SSMLValidationError(
                        "<phoneme> requires non-empty alphabet and ph attributes."
                    )
                if len(phonemes) > MAX_PHONEME_CHARACTERS:
                    raise SSMLValidationError(
                        f"<phoneme ph> is limited to {MAX_PHONEME_CHARACTERS} characters."
                    )
                if render_phoneme is None:
                    raise SSMLValidationError("<phoneme> is not enabled by this processor profile.")
                try:
                    rendered = render_phoneme(
                        alphabet,
                        phonemes,
                        source_text,
                        context.language,
                    )
                except ValueError as exc:
                    raise SSMLValidationError(str(exc)) from exc
                if not rendered.strip():
                    raise SSMLValidationError(
                        "The configured phoneme renderer returned empty text."
                    )
                _append_speech(units, rendered, context)
            else:
                raise SSMLValidationError(f"Unsupported SSML element <{tag}>.")
            _append_speech(units, element.tail or "", context)
            if len(units) > MAX_SSML_UNITS:
                raise SSMLValidationError(f"SSML is limited to {MAX_SSML_UNITS} synthesis units.")

    walk(root, _Context(root_language, root_language_explicit, default_voice), 0)
    if not units:
        raise SSMLValidationError("SSML input must contain speech or a break.")
    return SSMLPlan(input_type=input_type, units=tuple(units), voice_definitions=definitions)


def validate_ssml(
    document: str,
    input_type: Literal["ssml", "ssml-h"],
    *,
    default_language: str | None = None,
    default_voice: str | None = None,
    resolve_language: LanguageResolver | None = None,
    validate_voice: VoiceValidator | None = None,
    render_phoneme: PhonemeRenderer | None = None,
    allow_turn_direction: bool = False,
) -> SSMLPlan:
    """Validate and compile a document into an immutable synthesis plan."""

    return compile_ssml(
        document,
        input_type,
        default_language=default_language,
        default_voice=default_voice,
        resolve_language=resolve_language,
        validate_voice=validate_voice,
        render_phoneme=render_phoneme,
        allow_turn_direction=allow_turn_direction,
    )


def ssml_capabilities(
    *,
    phoneme_alphabets: tuple[str, ...] = (),
    description_supported: bool = True,
    turn_direction_supported: bool = False,
) -> dict:
    return {
        "input_types": ["text", "ssml", "ssml-h"],
        "ssml": {
            "version": "1.1-compatible subset",
            "namespace": SSML_NAMESPACE,
            "elements": [
                "speak",
                "metadata",
                "p",
                "s",
                "token",
                "w",
                "voice",
                "lang",
                "break",
                "prosody",
                "sub",
                "say-as",
                *(["phoneme"] if phoneme_alphabets else []),
            ],
            "say_as": ["characters", "digits", "cardinal", "ordinal (English)"],
            "phoneme_alphabets": list(phoneme_alphabets),
        },
        "ssml_h": {
            "version": "1.0",
            "namespace": SSML_H_NAMESPACE,
            "prefix_example": "h",
            "extensions": ["voice-definition", "description", "sample"],
            "voice_scopes": ["request", "profile"],
            "description_supported": description_supported,
            "turn_direction": {
                "supported": turn_direction_supported,
                "attribute": "h:direction",
                "element": "voice",
                "max_characters": MAX_TURN_DIRECTION_CHARACTERS,
            },
            "specification": "https://hangrylabs.app/ns/ssml-h/1.0",
        },
        "limits": {
            "source_characters": MAX_SSML_SOURCE_CHARACTERS,
            "elements": MAX_SSML_ELEMENTS,
            "nesting": MAX_SSML_NESTING,
            "synthesis_units": MAX_SSML_UNITS,
            "voice_definitions": MAX_SSML_VOICE_DEFINITIONS,
            "break_ms": MAX_BREAK_MS,
            "total_break_ms": MAX_TOTAL_BREAK_MS,
            "voice_sample_characters": MAX_VOICE_SAMPLE_CHARACTERS,
            "turn_direction_characters": MAX_TURN_DIRECTION_CHARACTERS,
        },
    }
