from __future__ import annotations

import unittest

from ssml_h import (
    MAX_BREAK_MS,
    MAX_SSML_NESTING,
    MAX_TURN_DIRECTION_CHARACTERS,
    SSML_H_NAMESPACE,
    SSMLValidationError,
    ssml_capabilities,
    validate_ssml,
)


def resolve_language(value: str) -> str:
    aliases = {"en-US": "en", "pl-PL": "pl"}
    if value in {"en", "pl"}:
        return value
    if value not in aliases:
        raise ValueError(f"Unsupported language '{value}'.")
    return aliases[value]


class ParserTests(unittest.TestCase):
    def test_standard_controls_compile_in_document_order(self) -> None:
        plan = validate_ssml(
            """<speak version="1.1" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
              Hello <sub alias="World Wide Web Consortium">W3C</sub>.
              <break time="500ms"/>
              Attempt <say-as interpret-as="ordinal">3</say-as> by
              <say-as interpret-as="characters">API</say-as>.
            </speak>""",
            "ssml",
            resolve_language=resolve_language,
        )

        self.assertEqual([unit.kind for unit in plan.units], ["speech", "break", "speech"])
        self.assertIn("World Wide Web Consortium", plan.units[0].text)
        self.assertEqual(plan.units[1].duration_ms, 500)
        self.assertIn("3rd", plan.units[2].text)
        self.assertIn("A P I", plan.units[2].text)

    def test_ssml_h_voice_definition_compiles(self) -> None:
        plan = validate_ssml(
            f"""<speak version="1.1" xmlns="http://www.w3.org/2001/10/synthesis"
                xmlns:h="{SSML_H_NAMESPACE}" xml:lang="en-US">
              <metadata><h:extensions version="1.0">
                <h:voice-definition name="Bob" gender="male" age="elderly"
                  accent="american" scope="profile" replace="true" seed="42">
                  <h:sample xml:lang="en-US">My name is Bob.</h:sample>
                </h:voice-definition>
              </h:extensions></metadata>
              <voice name="Bob" required="name">Are we ready?</voice>
            </speak>""",
            "ssml-h",
            resolve_language=resolve_language,
        )

        definition = plan.voice_definitions[0]
        self.assertEqual(definition.name, "Bob")
        self.assertEqual(definition.scope, "profile")
        self.assertTrue(definition.replace)
        self.assertEqual(definition.seed, 42)
        self.assertEqual(definition.sample, "My name is Bob.")
        self.assertEqual(plan.units[0].voice, "Bob")

    def test_ssml_h_requires_explicit_mode(self) -> None:
        document = f"""<speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:h="{SSML_H_NAMESPACE}">
          <metadata><h:extensions version="1.0"><h:voice-definition name="Bob" gender="male"/></h:extensions></metadata>
          Hello.
        </speak>"""
        with self.assertRaisesRegex(SSMLValidationError, "input_type='ssml-h'"):
            validate_ssml(document, "ssml")

    def test_ssml_h_turn_direction_is_capability_gated_and_normalized(self) -> None:
        document = f"""<speak version="1.1" xmlns="http://www.w3.org/2001/10/synthesis"
            xmlns:h="{SSML_H_NAMESPACE}">
          <voice name="Host" h:direction="  Bright   and delighted  ">
            Opening. <prosody rate="slow">Measured detail.</prosody>
            <voice name="Guest">A separate voice.</voice> Closing.
          </voice>
        </speak>"""

        with self.assertRaisesRegex(SSMLValidationError, "not enabled"):
            validate_ssml(document, "ssml-h", validate_voice=lambda _name, _definitions: None)

        plan = validate_ssml(
            document,
            "ssml-h",
            validate_voice=lambda _name, _definitions: None,
            allow_turn_direction=True,
        )

        self.assertEqual(
            [(unit.voice, unit.direction) for unit in plan.units],
            [
                ("Host", "Bright and delighted"),
                ("Host", "Bright and delighted"),
                ("Guest", None),
                ("Host", "Bright and delighted"),
            ],
        )

    def test_ssml_h_direction_can_design_the_default_voice_for_a_sentence(self) -> None:
        document = f'''<speak version="1.1" xmlns="http://www.w3.org/2001/10/synthesis"
            xmlns:h="{SSML_H_NAMESPACE}">
          <s h:direction="  Warm   middle-aged narrator  ">Welcome aboard.</s>
        </speak>'''

        plan = validate_ssml(document, "ssml-h", allow_turn_direction=True)

        self.assertIsNone(plan.units[0].voice)
        self.assertEqual(plan.units[0].direction, "Warm middle-aged narrator")

    def test_turn_direction_rejects_invalid_mode_namespace_and_bounds(self) -> None:
        namespaced = (
            f'<speak xmlns:h="{SSML_H_NAMESPACE}">'
            '<voice name="Host" h:direction="Calm">Hello.</voice></speak>'
        )
        with self.assertRaisesRegex(SSMLValidationError, "requires input_type='ssml-h'"):
            validate_ssml(namespaced, "ssml", allow_turn_direction=True)

        bare = '<speak version="1.1"><voice name="Host" direction="Calm">Hello.</voice></speak>'
        with self.assertRaisesRegex(SSMLValidationError, "Unsupported attribute"):
            validate_ssml(bare, "ssml-h", allow_turn_direction=True)

        empty = (
            f'<speak version="1.1" xmlns:h="{SSML_H_NAMESPACE}">'
            '<voice name="Host" h:direction="  ">Hello.</voice></speak>'
        )
        with self.assertRaisesRegex(SSMLValidationError, "must not be empty"):
            validate_ssml(empty, "ssml-h", allow_turn_direction=True)

        oversized = "x" * (MAX_TURN_DIRECTION_CHARACTERS + 1)
        too_long = (
            f'<speak version="1.1" xmlns:h="{SSML_H_NAMESPACE}">'
            f'<voice name="Host" h:direction="{oversized}">Hello.</voice></speak>'
        )
        with self.assertRaisesRegex(SSMLValidationError, "limited"):
            validate_ssml(too_long, "ssml-h", allow_turn_direction=True)

    def test_capabilities_report_turn_direction_opt_in(self) -> None:
        disabled = ssml_capabilities()
        enabled = ssml_capabilities(turn_direction_supported=True)

        self.assertFalse(disabled["ssml_h"]["turn_direction"]["supported"])
        self.assertTrue(enabled["ssml_h"]["turn_direction"]["supported"])
        self.assertEqual(enabled["ssml_h"]["turn_direction"]["elements"], ["voice", "s"])
        self.assertEqual(
            enabled["limits"]["turn_direction_characters"],
            MAX_TURN_DIRECTION_CHARACTERS,
        )

    def test_language_voice_and_nested_prosody_are_inherited(self) -> None:
        plan = validate_ssml(
            """<speak version="1.1" xml:lang="en-US">
              Root.
              <voice name="known"><lang xml:lang="pl-PL">Cześć.</lang></voice>
              <prosody rate="80%" pitch="+2st" volume="-3dB">
                Styled <prosody rate="125%" pitch="-1st">nested.</prosody>
              </prosody>
            </speak>""",
            "ssml",
            resolve_language=resolve_language,
            validate_voice=lambda name, _: (
                None if name == "known" else (_ for _ in ()).throw(ValueError("missing"))
            ),
        )

        polish = next(unit for unit in plan.units if "Cześć" in unit.text)
        nested = next(unit for unit in plan.units if "nested" in unit.text)
        self.assertEqual((polish.language, polish.voice), ("pl", "known"))
        self.assertAlmostEqual(nested.prosody.rate, 1.0)
        self.assertAlmostEqual(nested.prosody.pitch_semitones, 1.0)

    def test_phoneme_requires_processor_renderer(self) -> None:
        document = '<speak xml:lang="en-US">I will <phoneme alphabet="x-arpabet" ph="R EH1 D">read</phoneme>.</speak>'
        with self.assertRaisesRegex(SSMLValidationError, "not enabled"):
            validate_ssml(document, "ssml", resolve_language=resolve_language)

        calls: list[tuple[str, str, str, str | None]] = []

        def render(alphabet: str, ph: str, source: str, language: str | None) -> str:
            calls.append((alphabet, ph, source, language))
            return f"[{ph.upper()}]"

        plan = validate_ssml(
            document,
            "ssml",
            resolve_language=resolve_language,
            render_phoneme=render,
        )
        self.assertEqual(calls, [("x-arpabet", "R EH1 D", "read", "en")])
        self.assertIn("[R EH1 D]", plan.units[0].text)

    def test_unsafe_xml_and_resource_limits_are_rejected(self) -> None:
        with self.assertRaisesRegex(SSMLValidationError, "DTD"):
            validate_ssml('<!DOCTYPE speak [<!ENTITY x "hello">]><speak>&x;</speak>', "ssml")
        with self.assertRaisesRegex(SSMLValidationError, "Each <break>"):
            validate_ssml(f'<speak><break time="{MAX_BREAK_MS + 1}ms"/></speak>', "ssml")
        content = "Hello."
        for _ in range(MAX_SSML_NESTING + 1):
            content = f'<prosody rate="100%">{content}</prosody>'
        with self.assertRaisesRegex(SSMLValidationError, "nesting"):
            validate_ssml(f"<speak>{content}</speak>", "ssml")


if __name__ == "__main__":
    unittest.main()
