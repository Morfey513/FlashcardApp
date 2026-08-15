import logging

from src.utils import logger_setup


def test_setup_logging_replaces_handlers_and_writes_utf8_log(tmp_path, monkeypatch):
    log_dir = tmp_path / "nested" / "logs"
    log_file = log_dir / "app.log"
    monkeypatch.setattr(logger_setup, "LOG_DIR", log_dir)
    monkeypatch.setattr(logger_setup, "LOG_FILE", log_file)
    root = logging.Logger("isolated-utility-test")
    previous = logging.StreamHandler()
    root.addHandler(previous)
    monkeypatch.setattr(logger_setup.logging, "getLogger", lambda: root)

    try:
        logger_setup.setup_logging()
        assert previous._closed is True
        first_handlers = list(root.handlers)
        assert len(first_handlers) == 2
        assert {handler.level for handler in first_handlers} == {
            logging.DEBUG,
            logging.INFO,
        }

        # Reconfiguration replaces and closes old handlers instead of duplicating them.
        logger_setup.setup_logging()
        assert len(root.handlers) == 2
        assert all(handler not in root.handlers for handler in first_handlers)
        root.warning("Unicode message: café")
        for handler in root.handlers:
            handler.flush()
        assert "Unicode message: café" in log_file.read_text(encoding="utf-8")
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers.clear()
