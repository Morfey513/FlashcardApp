# README screenshots

Generate the current screenshots from a normal graphical Windows session:

```powershell
.\.venv\Scripts\python.exe tools\capture_readme_screenshots.py
```

The script captures every top-level dialog and primary screen: guest/student/
admin launchers, login, registration, settings, account settings, progress,
quiz and flashcard selection, both editors, both moderation tabs, account
suspension, and image preview (when sample media exists).

Review the generated images, delete any state you do not want to publish, then
commit the remaining captures with the related README update.
