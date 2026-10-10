from __future__ import annotations

import unittest

from ssml_h import SSMLBuilder, SSMLValidationError


class BuilderTests(unittest.TestCase):
    def test_builds_and_validates_nested_standard_ssml(self) -> None:
        document = SSMLBuilder(language="en-US")
        document.text("Hello & welcome. ")
        document.break_(milliseconds=250)
        with document.prosody(rate="slow", volume="-3dB") as styled:
            styled.text("Use <safe> XML.")

        xml = document.build()
        plan = document.validate()

        self.assertIn("Hello &amp; welcome", xml)
        self.assertIn("Use &lt;safe&gt; XML", xml)
        self.assertEqual([unit.kind for unit in plan.units], ["speech", "break", "speech"])

    def test_builds_dynamic_voice_metadata_before_content(self) -> None:
        document = SSMLBuilder.ssml_h(language="en-US")
        document.text("Opening narration. ")
        with document.voice("Bob") as bob:
            bob.text("Are we ready?")
        document.define_voice(
            "Bob",
            gender="male",
            age="elderly",
            accent="american",
            scope="profile",
            seed=42,
            sample="My name is Bob.",
            sample_language="en-US",
        )

        xml = document.build()
        plan = document.validate()

        self.assertLess(xml.index("metadata"), xml.index("voice name"))
        self.assertIn('scope="profile"', xml)
        self.assertEqual(plan.voice_definitions[0].name, "Bob")
        self.assertTrue(plan.units[0].text.startswith("Opening narration"))

    def test_profile_persistence_is_never_implicit(self) -> None:
        document = SSMLBuilder.ssml_h()
        document.define_voice("Temporary", gender="female")
        document.voice("Temporary").text("Hello.")

        plan = document.validate()

        self.assertEqual(plan.voice_definitions[0].scope, "request")
        self.assertNotIn("replace=", document.build())

    def test_builds_namespaced_turn_direction(self) -> None:
        document = SSMLBuilder.ssml_h(language="en-US")
        with document.voice("Host", direction="  Calm   and authoritative  ") as host:
            host.text("Welcome back.")

        xml = document.build()
        plan = document.validate(
            allow_turn_direction=True,
            validate_voice=lambda _name, _definitions: None,
        )

        self.assertIn('h:direction="Calm and authoritative"', xml)
        self.assertEqual(plan.units[0].direction, "Calm and authoritative")

    def test_turn_direction_builder_requires_ssml_h(self) -> None:
        document = SSMLBuilder()
        with self.assertRaisesRegex(ValueError, "requires input_type='ssml-h'"):
            document.voice("Host", direction="Calm")

    def test_builds_direction_only_sentence(self) -> None:
        document = SSMLBuilder.ssml_h(language="en-US")
        document.sentence(direction="  Low and thoughtful  ").text("A new voice.")

        xml = document.build()
        plan = document.validate(allow_turn_direction=True)

        self.assertIn('h:direction="Low and thoughtful"', xml)
        self.assertIsNone(plan.units[0].voice)
        self.assertEqual(plan.units[0].direction, "Low and thoughtful")

    def test_rejects_invalid_break_builder_arguments(self) -> None:
        document = SSMLBuilder()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            document.break_(milliseconds=100, strength="weak")
        with self.assertRaisesRegex(ValueError, "negative"):
            document.break_(milliseconds=-1)

    def test_builder_output_still_uses_validator_limits(self) -> None:
        document = SSMLBuilder.ssml_h()
        document.define_voice("Invalid", gender="female", scope="request", replace=True)
        document.voice("Invalid").text("Hello.")
        with self.assertRaisesRegex(SSMLValidationError, "scope='profile'"):
            document.validate()


if __name__ == "__main__":
    unittest.main()
