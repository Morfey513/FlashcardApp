# FlashcardApp — Codex Project Instructions

## Project

FlashcardApp is a Python/PyQt6 flashcard and quiz application.

The project is being developed toward a client/server architecture with
PostgreSQL persistence.

---

# Architecture

Main application areas include:

- PyQt6 UI;
- application/business logic;
- persistence/repositories;
- flashcard functionality;
- quiz functionality;
- authentication and roles;
- PostgreSQL;
- tests.

Before making architectural changes, consult the relevant documentation in
`docs/`.

---

# Project Documentation

Use these documents as the primary source of project architecture:

- `docs/architecture.md`
- `docs/database.md`
- `docs/testing.md`

Do not duplicate large sections of these documents in this file.

If documentation contradicts the current implementation, investigate before
making a major architectural decision.

---

# PostgreSQL

PostgreSQL is the intended persistent database.

The PostgreSQL implementation is substantially complete.

Do not redesign the database schema unnecessarily.

Before changing:

- tables;
- relationships;
- constraints;
- indexes;
- migrations;

inspect the existing schema and `docs/database.md`.

Prefer incremental changes over unnecessary schema redesign.

---

# UI

The UI is implemented with PyQt6.

UI changes should remain within the presentation layer unless the requested
behavior genuinely requires application/business-logic changes.

Avoid mixing database access directly into UI widgets.

---

# Business Logic

Business rules should remain outside UI widgets whenever practical.

Prefer the existing project architecture rather than introducing new
architectural patterns for small changes.

---

# Testing

The project uses pytest.

Relevant tests should be updated when behavior changes.

Do not weaken or remove tests merely to make an implementation pass.

Run the smallest relevant test set first, followed by the broader suite when
appropriate.

---

# Scope

Avoid unrelated refactoring.

Do not modify unrelated modules simply because improvements are noticed.

If a larger architectural problem is discovered, report it rather than
silently expanding the task.

---

# Git

Keep changes focused.

Before finishing:

- inspect the diff;
- verify no unrelated files were modified;
- run appropriate tests.