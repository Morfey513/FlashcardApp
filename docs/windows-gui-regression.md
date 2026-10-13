# Visible Windows GUI regression

This is an opt-in desktop regression runner; it is not collected by pytest.
It starts one visible FlashcardApp process with one QApplication, plus a
loopback API backed only by the disposable `study_buddy_test` database.

Install the separate tooling dependencies and run on an unlocked Windows desktop:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
$env:STUDY_BUDDY_TEST_DATABASE_URL = '<dedicated test database URL>'
.\.venv\Scripts\python.exe -m tools.gui_regression --profile diagnostic --validation no-uia --hold-seconds 30
.\.venv\Scripts\python.exe -m tools.gui_regression --profile diagnostic --validation uia --repetitions 5 --hold-seconds 30
```

After those launcher checks are clean, run the bounded initial login/viewer/logout
path with `--profile diagnostic --scenario minimal_milestone`, then the visible
role matrix with `--profile smoke`. `phase7` is opt-in and uses the configured
iteration counts. Unless `--artifacts` is supplied, results are stored under
`.temp/artifacts/windows-gui/`.

Run only the verified guest/student authentication path with:

```powershell
.\.venv\Scripts\python.exe -m tools.gui_regression --profile diagnostic --scenario authentication_milestone
```

The Windows UIA login contract is: launcher Button `🔑`; owned Window `LOGIN`;
two Edit descendants ordered Email then Password; Button `Sign In`; optional
Button `Continue as Guest`; launcher Button `🚪`; owned Window `Log out?`; and
Button `Yes`. Guest/authenticated state is asserted through the welcome Text and
the mutually exclusive login/logout buttons.

The launcher manifest uses the rendered English UIA names, including emoji:
`📝 Quiz Mode`, `🎴 Flashcard Mode`, `My Progress`, `📝 Quiz Editor`,
`🏫 My Classes / Roster`, and `🛡️ Moderation`. Study windows return through
their rendered `← Return to Launcher` command. These are semantic UIA names,
not screen coordinates or translation-key assumptions.

The runner requires pywinauto UI Automation locators; it does not use fixed
screen coordinates. A missing rendered control is a reported automation
limitation, not a skipped pass. It copies the desktop runtime into a temporary
directory, uses prefix-owned PostgreSQL fixtures, and removes only those
fixtures during cleanup. Secrets are redacted from generated artifacts.

For the default smoke matrix, the copied guest runtime exposes exactly one
quiz and one flashcard deck, while the API-backed student fixture exposes
exactly one public quiz and one public deck. Their run-specific identities are
recorded in `fixture-identities.json`. This is intentional: the current Qt
provider exposes `QListWidget` rows as anonymous UIA `ListItem`s, so two visible
quizzes cannot be selected by semantic name without a production accessibility
change. The runner therefore verifies singleton fixture cardinality before it
interacts; it never chooses an arbitrary first row. Class-only assessment
fixtures are opt-in for a dedicated assessment scenario and are not included
in the default smoke data.

The runner first uses Win32/PID responsiveness checks, then attaches UIA to the
observed HWND. It records natural exits, normal `WM_CLOSE` shutdowns, and
runner-forced termination separately. Do not run it while the desktop is locked, through a disconnected RDP session,
or against production/development data. A `0xC0000005` or `0xC0000409` exit
stops the run immediately and preserves stdout/stderr, app logs, screenshots,
the UIA tree, and relevant Windows Application/WER events. A passing run is
bounded regression evidence, not proof that native Qt crashes are resolved.

The runner also preserves first-chance Windows diagnostics from the desktop
stderr. `0x8001010d` is recorded as a non-fatal UIA/COM diagnostic only when
the real HWND-owning process remained responsive, exited normally, and no
matching WER crash event exists. It is never suppressed. Any other diagnostic,
matching WER event, or native crash exit requires review. Optional ProcDump
attaches to the HWND-owning Qt process rather than a Python launcher wrapper.

If Sysinternals ProcDump is installed, pass `--procdump C:\path\to\procdump.exe`
to collect a full dump for an unexpected native desktop-process exit.
