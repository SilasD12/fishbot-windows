"""PyQt6 GUI front-end for fishbot on Windows.

Wraps the CLI in `fishbot.main`. Spawns the bot as a managed QProcess child,
mirrors every argparse flag as a checkbox, and streams the bot's merged
stdout/stderr into a log panel.

The Start button launches `fishbot.exe` (when running from a PyInstaller
build) or `python -m fishbot.main` (in dev mode). The Stop button asks the
child to terminate, then escalates to a hard kill if it doesn't exit.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyQt6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
from PyQt6.QtGui import QCloseEvent, QFont, QFontDatabase, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fishbot import paths
from fishbot.main import build_arg_parser

TERMINATE_GRACE_MS = 5000
KILL_GRACE_MS = 3000


def _bool_flag_actions(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    out: list[argparse.Action] = []
    for action in parser._actions:
        if isinstance(action, argparse._StoreTrueAction):
            out.append(action)
    return out


def _longest_option(action: argparse.Action) -> str:
    for opt in action.option_strings:
        if opt.startswith("--"):
            return opt
    return action.option_strings[0]


def _resolve_bot_command() -> tuple[str, list[str]]:
    """Return (program, prefix_args) used to spawn the bot child process.

    Frozen install: <install>/fishbot.exe with no prefix args.
    Dev mode:      python -m fishbot.main
    """
    if getattr(sys, "frozen", False):
        bot_exe = paths.install_dir() / "fishbot.exe"
        if bot_exe.exists():
            return str(bot_exe), []
        # Some PyInstaller layouts put the CLI exe in a sibling subdir.
        alt = paths.install_dir() / "fishbot" / "fishbot.exe"
        if alt.exists():
            return str(alt), []
    return sys.executable, ["-m", "fishbot.main"]


class FishbotWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Fishbot")
        self.resize(820, 640)

        self._parser = build_arg_parser()
        self._proc: QProcess | None = None
        self._stopping = False
        self._terminate_timer: QTimer | None = None
        self._kill_timer: QTimer | None = None

        # Make sure %APPDATA%\Fishbot\config.toml exists (seeded from bundled).
        paths.ensure_user_dirs()
        self._default_config = paths.ensure_user_config()

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_config_row())
        root.addWidget(self._build_flags_box())
        root.addLayout(self._build_control_row())
        root.addWidget(QLabel("Output"))
        root.addWidget(self._build_log_panel(), stretch=1)
        root.addLayout(self._build_log_controls_row())

    def _build_config_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Config:"))
        self.config_edit = QLineEdit(str(self._default_config))
        row.addWidget(self.config_edit, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._on_browse_config)
        row.addWidget(browse)
        return row

    def _build_flags_box(self) -> QGroupBox:
        box = QGroupBox("Options")
        layout = QVBoxLayout(box)
        self.flag_checks: dict[str, QCheckBox] = {}
        for action in _bool_flag_actions(self._parser):
            flag = _longest_option(action)
            label = f"{flag}  —  {action.help}" if action.help else flag
            check = QCheckBox(label)
            self.flag_checks[flag] = check
            layout.addWidget(check)
        return box

    def _build_control_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        self.calibrate_btn = QPushButton("Calibrate…")
        self.calibrate_btn.clicked.connect(self._on_calibrate)
        self.status_label = QLabel("Idle")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.calibrate_btn)
        row.addStretch(1)
        row.addWidget(self.status_label)
        return row

    def _build_log_panel(self) -> QPlainTextEdit:
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        mono: QFont = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.log.setFont(mono)
        return self.log

    def _build_log_controls_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.autoscroll_check = QCheckBox("Auto-scroll")
        self.autoscroll_check.setChecked(True)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.log.clear)
        row.addWidget(self.autoscroll_check)
        row.addStretch(1)
        row.addWidget(clear_btn)
        return row

    def _on_browse_config(self) -> None:
        current = self.config_edit.text().strip() or str(self._default_config)
        start_dir = str(Path(current).parent if current else paths.install_dir())
        path, _ = QFileDialog.getOpenFileName(
            self, "Select config.toml", start_dir, "TOML (*.toml);;All files (*)"
        )
        if path:
            self.config_edit.setText(path)

    def _build_args(self) -> list[str]:
        args: list[str] = []
        config_path = self.config_edit.text().strip()
        if config_path:
            args += ["--config", config_path]
        for flag, check in self.flag_checks.items():
            if check.isChecked():
                args.append(flag)
        return args

    def _on_start(self) -> None:
        if self._proc is not None:
            return

        config_path = self.config_edit.text().strip()
        if not config_path or not Path(config_path).exists():
            QMessageBox.warning(self, "Fishbot", f"Config file not found:\n{config_path}")
            return

        program, prefix = _resolve_bot_command()
        argv = [*prefix, *self._build_args()]
        printable = " ".join([program, *argv])
        self._append_log(f"$ {printable}\n")

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.setWorkingDirectory(str(paths.install_dir()))

        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        proc.setProcessEnvironment(env)

        proc.readyRead.connect(self._on_ready_read)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)

        self._proc = proc
        self._stopping = False
        proc.start(program, argv)
        if not proc.waitForStarted(3000):
            self._append_log(f"--- failed to start `{program}`\n")
            self._proc = None
            return

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.calibrate_btn.setEnabled(False)
        self.status_label.setText("Running")

    def _on_stop(self) -> None:
        if self._proc is None or self._stopping:
            return
        self._stopping = True
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Stopping…")
        # On Windows QProcess.terminate() sends WM_CLOSE to top-level windows
        # of the child; for a windowless console child like fishbot.exe this
        # falls back to TerminateProcess. The bot is interruption-safe (no
        # in-flight transactions, all progress is per-cast), so a hard stop
        # here is acceptable. We still escalate to kill() in case terminate()
        # silently does nothing on a stuck child.
        self._proc.terminate()
        self._append_log("--- requested stop\n")
        self._terminate_timer = QTimer(self)
        self._terminate_timer.setSingleShot(True)
        self._terminate_timer.timeout.connect(self._escalate_kill)
        self._terminate_timer.start(TERMINATE_GRACE_MS)

    def _escalate_kill(self) -> None:
        if self._proc is None or self._proc.state() == QProcess.ProcessState.NotRunning:
            return
        self._append_log("--- still running, force-killing\n")
        self._proc.kill()
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.start(KILL_GRACE_MS)

    def _on_ready_read(self) -> None:
        if self._proc is None:
            return
        data = bytes(self._proc.readAll()).decode("utf-8", errors="replace")
        if data:
            self._append_log(data)

    def _on_error(self, err: QProcess.ProcessError) -> None:
        self._append_log(f"--- process error: {err.name}\n")

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        status_word = "exited" if exit_status == QProcess.ExitStatus.NormalExit else "crashed"
        self._append_log(f"--- {status_word} (code {exit_code})\n")
        for timer_attr in ("_terminate_timer", "_kill_timer"):
            t = getattr(self, timer_attr)
            if t is not None:
                t.stop()
                setattr(self, timer_attr, None)
        self._proc = None
        self._stopping = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.calibrate_btn.setEnabled(True)
        self.status_label.setText(f"Exited ({exit_code})")

    def _append_log(self, text: str) -> None:
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        if self.autoscroll_check.isChecked():
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _on_calibrate(self) -> None:
        if self._proc is not None:
            QMessageBox.information(
                self, "Fishbot",
                "Stop the bot before calibrating.",
            )
            return
        # Run the calibrate flow in this same Qt application so the overlay
        # and the main window share an event loop.
        try:
            from fishbot.calibrate import main as calibrate_main
            rc = calibrate_main()
            self._append_log(f"--- calibrate exited (code {rc})\n")
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"--- calibrate failed: {exc}\n")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._proc is None:
            event.accept()
            return
        reply = QMessageBox.question(
            self,
            "Fishbot",
            "Bot is still running. Stop it and exit?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        self._on_stop()
        if self._proc is not None:
            self._proc.waitForFinished(TERMINATE_GRACE_MS + KILL_GRACE_MS + 1000)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    win = FishbotWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
