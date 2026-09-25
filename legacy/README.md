# Legacy data

This directory preserves historical/demo content that is no longer indexed by
the running application. It is retained for reference and manual migration
experiments; runtime repositories do not scan this directory.

- `data/quizzes/` contains retired quiz packages, including their historical
  attempts, moderation records, and media.
- `data/flashcards/` contains retired flashcard packages and media.

Historical attempts, unused media, or pre-demo moderation records belonging to
the retained canonical IDs are archived here as well; the active package keeps
only the state and assets required by the demonstration.

Current offline/demo content remains under `data/` and is listed by
`data/quizzes.json` and `data/flashcard_decks.json`. Tests should create their
own isolated fixtures under pytest temporary directories rather than adding
runtime entries here.
