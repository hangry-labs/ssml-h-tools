from __future__ import annotations

import unittest

from ssml_h import (
    MAX_BREAK_MS,
    MAX_SSML_NESTING,
    SSML_H_NAMESPACE,
    SSMLValidationError,
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
