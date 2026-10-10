# Changelog

All notable changes to this project will be documented in this file.

## 0.3.1 - 2026-10-10

- Preserve the singular `turn_direction.element` capability field for 0.2.x
  consumers while advertising the expanded support through `elements`.

## 0.3.0 - 2026-10-10

- Allow capability-gated `h:direction` on `<s>` to design or direct the
  processor's default voice without first naming a voice.
- Add `sentence(direction=...)` builder support and advertise both supported
  direction-bearing elements through capability discovery.

## 0.2.0 - 2026-10-08

- Add capability-gated SSML-H `h:direction` parsing for individual voice turns.
- Add immutable per-unit direction data with bounded, normalized values.
- Add namespace-safe `direction=` support to the document builder.
- Advertise turn-direction support and limits through capability discovery.

## 0.1.0 - 2026-10-06

- Add hardened SSML and SSML-H parsing.
- Add immutable synthesis plan types.
- Add namespace-safe document builder.
- Add host callbacks for language, voice, and phoneme capabilities.
