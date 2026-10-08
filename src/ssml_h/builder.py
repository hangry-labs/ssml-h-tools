from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree as ET

from .parser import (
    MAX_TURN_DIRECTION_CHARACTERS,
    SSML_H_NAMESPACE,
    SSML_NAMESPACE,
    XML_LANGUAGE_ATTRIBUTE,
    SSMLPlan,
    compile_ssml,
)

ET.register_namespace("", SSML_NAMESPACE)
ET.register_namespace("h", SSML_H_NAMESPACE)


def _qname(local: str, namespace: str = SSML_NAMESPACE) -> str:
    return f"{{{namespace}}}{local}"


def _stringify(value: str | int | float) -> str:
    return str(value).strip()


def _append_text(element: ET.Element, value: str) -> None:
    if not value:
        return
    children = list(element)
    if children:
        children[-1].tail = (children[-1].tail or "") + value
    else:
        element.text = (element.text or "") + value


@dataclass(frozen=True)
class VoiceDefinition:
    name: str
    scope: Literal["request", "profile"] = "request"
    replace: bool = False
    seed: int | None = None
    gender: str | None = None
    age: str | int | None = None
    pitch: str | None = None
    style: str | None = None
    languages: tuple[str, ...] = ()
    accent: str | None = None
    dialect: str | None = None
    description: str | None = None
    sample: str | None = None
    sample_language: str | None = None


class SSMLNode:
    """A synthesis node used to build nested SSML content safely."""

    def __init__(self, element: ET.Element, input_type: Literal["ssml", "ssml-h"] = "ssml"):
        self._element = element
        self._input_type = input_type

    def __enter__(self) -> SSMLNode:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback

    def text(self, value: str) -> SSMLNode:
        _append_text(self._element, value)
        return self

    def _child(self, tag: str, attributes: dict[str, str] | None = None) -> SSMLNode:
        return SSMLNode(
            ET.SubElement(self._element, _qname(tag), attributes or {}),
            self._input_type,
        )

    def paragraph(self, *, language: str | None = None) -> SSMLNode:
        attributes = {XML_LANGUAGE_ATTRIBUTE: language} if language else {}
        return self._child("p", attributes)

    def sentence(self, *, language: str | None = None) -> SSMLNode:
        attributes = {XML_LANGUAGE_ATTRIBUTE: language} if language else {}
        return self._child("s", attributes)

    def token(self) -> SSMLNode:
        return self._child("token")

    def voice(
        self,
        name: str,
        *,
        required: str | None = None,
        direction: str | None = None,
    ) -> SSMLNode:
        attributes = {"name": name}
        if required is not None:
            attributes["required"] = required
        if direction is not None:
            if self._input_type != "ssml-h":
                raise ValueError("Turn direction requires input_type='ssml-h'.")
            normalized = " ".join(direction.split()).strip()
            if not normalized:
                raise ValueError("direction must not be empty.")
            if len(normalized) > MAX_TURN_DIRECTION_CHARACTERS:
                raise ValueError(
                    f"direction is limited to {MAX_TURN_DIRECTION_CHARACTERS} characters."
                )
            attributes[_qname("direction", SSML_H_NAMESPACE)] = normalized
        return self._child("voice", attributes)

    def language(self, language: str) -> SSMLNode:
        return self._child("lang", {XML_LANGUAGE_ATTRIBUTE: language})

    def prosody(
        self,
        *,
        rate: str | None = None,
        pitch: str | None = None,
        volume: str | None = None,
    ) -> SSMLNode:
        attributes = {
            key: value
            for key, value in {"rate": rate, "pitch": pitch, "volume": volume}.items()
            if value is not None
        }
        return self._child("prosody", attributes)

    def break_(
        self,
        *,
        milliseconds: int | float | None = None,
        time: str | None = None,
        strength: str | None = None,
    ) -> SSMLNode:
        supplied = sum(value is not None for value in (milliseconds, time, strength))
        if supplied != 1:
            raise ValueError("break_ requires exactly one of milliseconds, time, or strength.")
        if milliseconds is not None:
            if milliseconds < 0:
                raise ValueError("milliseconds must not be negative.")
            attributes = {"time": f"{milliseconds:g}ms"}
        elif time is not None:
            attributes = {"time": time}
        else:
            attributes = {"strength": strength or ""}
        ET.SubElement(self._element, _qname("break"), attributes)
        return self

    def substitution(self, text: str, *, alias: str) -> SSMLNode:
        element = ET.SubElement(self._element, _qname("sub"), {"alias": alias})
        element.text = text
        return self

    def say_as(self, text: str, *, interpret_as: str) -> SSMLNode:
        element = ET.SubElement(
            self._element,
            _qname("say-as"),
            {"interpret-as": interpret_as},
        )
        element.text = text
        return self

    def phoneme(self, text: str, *, alphabet: str, ph: str) -> SSMLNode:
        element = ET.SubElement(
            self._element,
            _qname("phoneme"),
            {"alphabet": alphabet, "ph": ph},
        )
        element.text = text
        return self


class SSMLBuilder(SSMLNode):
    """Build standard SSML or SSML-H without string-concatenating XML."""

    def __init__(
        self,
        *,
        input_type: Literal["ssml", "ssml-h"] = "ssml",
        language: str | None = None,
        version: str | None = None,
    ):
        if input_type not in {"ssml", "ssml-h"}:
            raise ValueError("input_type must be 'ssml' or 'ssml-h'.")
        resolved_version = version or "1.1"
        attributes = {"version": resolved_version}
        if language:
            attributes[XML_LANGUAGE_ATTRIBUTE] = language
        self.input_type = input_type
        self._definitions: list[VoiceDefinition] = []
        super().__init__(ET.Element(_qname("speak"), attributes), input_type)

    @classmethod
    def ssml_h(cls, *, language: str | None = None) -> SSMLBuilder:
        return cls(input_type="ssml-h", language=language, version="1.1")

    def define_voice(
        self,
        name: str,
        *,
        scope: Literal["request", "profile"] = "request",
        replace: bool = False,
        seed: int | None = None,
        gender: str | None = None,
        age: str | int | None = None,
        pitch: str | None = None,
        style: str | None = None,
        languages: tuple[str, ...] | list[str] = (),
        accent: str | None = None,
        dialect: str | None = None,
        description: str | None = None,
        sample: str | None = None,
        sample_language: str | None = None,
    ) -> SSMLBuilder:
        if self.input_type != "ssml-h":
            raise ValueError("Dynamic voice definitions require input_type='ssml-h'.")
        self._definitions.append(
            VoiceDefinition(
                name=name,
                scope=scope,
                replace=replace,
                seed=seed,
                gender=gender,
                age=age,
                pitch=pitch,
                style=style,
                languages=tuple(languages),
                accent=accent,
                dialect=dialect,
                description=description,
                sample=sample,
                sample_language=sample_language,
            )
        )
        return self

    @property
    def voice_definitions(self) -> tuple[VoiceDefinition, ...]:
        return tuple(self._definitions)

    def _document_element(self) -> ET.Element:
        root = copy.deepcopy(self._element)
        if not self._definitions:
            return root

        metadata = ET.Element(_qname("metadata"))
        extensions = ET.SubElement(
            metadata,
            _qname("extensions", SSML_H_NAMESPACE),
            {"version": "1.0"},
        )
        for definition in self._definitions:
            values: dict[str, str | int | None] = {
                "name": definition.name,
                "scope": definition.scope,
                "replace": "true" if definition.replace else None,
                "seed": definition.seed,
                "gender": definition.gender,
                "age": definition.age,
                "pitch": definition.pitch,
                "style": definition.style,
                "languages": " ".join(definition.languages) or None,
                "accent": definition.accent,
                "dialect": definition.dialect,
            }
            attributes = {
                key: _stringify(value) for key, value in values.items() if value is not None
            }
            voice = ET.SubElement(
                extensions,
                _qname("voice-definition", SSML_H_NAMESPACE),
                attributes,
            )
            if definition.description is not None:
                description = ET.SubElement(
                    voice,
                    _qname("description", SSML_H_NAMESPACE),
                )
                description.text = definition.description
            if definition.sample is not None:
                sample_attributes = (
                    {XML_LANGUAGE_ATTRIBUTE: definition.sample_language}
                    if definition.sample_language
                    else {}
                )
                sample = ET.SubElement(
                    voice,
                    _qname("sample", SSML_H_NAMESPACE),
                    sample_attributes,
                )
                sample.text = definition.sample
        leading_text = root.text
        root.text = None
        root.insert(0, metadata)
        metadata.tail = leading_text
        return root

    def build(self, *, xml_declaration: bool = False) -> str:
        return ET.tostring(
            self._document_element(),
            encoding="unicode",
            xml_declaration=xml_declaration,
            short_empty_elements=True,
        )

    def validate(self, **kwargs) -> SSMLPlan:
        return compile_ssml(self.build(), self.input_type, **kwargs)

    def __str__(self) -> str:
        return self.build()
