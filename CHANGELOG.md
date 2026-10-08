# Changelog

All notable changes to this project will be documented in this file.

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
