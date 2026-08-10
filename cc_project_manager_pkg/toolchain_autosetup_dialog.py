"""GUI dialog for one-time machine toolchain Auto-Setup."""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .toolchain_autosetup import (
    PINNED_COMPONENTS,
    TEROSHDL_EXTENSION_ID,
    apply_paths_to_project,
    run_autosetup,
    setup_vscode_and_teroshdl,
)


class _AutoSetupWorker(QThread):
    """Background worker: parallel downloads + extract + machine finalize."""

    component_progress = pyqtSignal(str, int, int, str)  # key, cur, total, status
    finished_ok = pyqtSignal(dict, list)  # resolved paths, setup notes
    finished_err = pyqtSignal(str)

    def __init__(self, install_root: str, install_vscode: bool, parent=None):
        super().__init__(parent)
        self.install_root = install_root
        self.install_vscode = install_vscode

    def run(self) -> None:
        try:
            def on_progress(key: str, cur: int, total: int, status: str) -> None:
                self.component_progress.emit(key, cur, total, status)

            resolved = run_autosetup(self.install_root, progress=on_progress, max_workers=3)
            self.component_progress.emit("oss_cad_suite", 1, 1, "Configuring machine environment…")
            notes = apply_paths_to_project(resolved, self.install_root)

            if self.install_vscode:
                notes.extend(
                    setup_vscode_and_teroshdl(self.install_root, progress=on_progress)
                )

            self.finished_ok.emit(resolved, notes)
        except Exception as e:
            self.finished_err.emit(str(e))


class AutoSetupToolchainDialog(QDialog):
    """One-time machine setup: download pinned tools and configure User PATH/env."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-Setup Toolchain (one-time)")
        self.setModal(True)
        self.resize(720, 640)
        self._worker: Optional[_AutoSetupWorker] = None
        self._bars: Dict[str, QProgressBar] = {}
        self._status: Dict[str, QLabel] = {}

        root = QVBoxLayout(self)

        intro = QLabel(
            "One-time machine setup for all future GateMate projects.\n"
            "Downloads pinned toolchain versions, then:\n"
            "• OSS CAD Suite — environment.ps1 + YOSYSHQ_ROOT / PATH "
            "(includes Yosys, nextpnr, gmpack, openFPGALoader, GTKWave)\n"
            "• GHDL — standalone Windows zip + User PATH\n"
            "• TerosHDL — writes ~/.teroshdl2_config.json (GHDL/Yosys/GTKWave paths)"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #AAAAAA;")
        root.addWidget(intro)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Install directory:"))
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText(r"e.g. C:\FPGA_Tools  (avoid spaces)")
        dir_row.addWidget(self.dir_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        dir_row.addWidget(browse)
        root.addLayout(dir_row)

        self.vscode_check = QCheckBox(
            f"Also install Visual Studio Code + TerosHDL ({TEROSHDL_EXTENSION_ID})"
        )
        self.vscode_check.setChecked(False)
        self.vscode_check.setToolTip(
            "If checked: detect VS Code, silently install the user setup if missing, "
            "then install the TerosHDL extension."
        )
        self.vscode_check.toggled.connect(self._on_vscode_toggled)
        root.addWidget(self.vscode_check)

        comps = QGroupBox("Pinned components (downloaded in parallel)")
        form = QFormLayout(comps)
        for comp in PINNED_COMPONENTS:
            self._add_progress_row(form, comp.key, f"{comp.title} — {comp.version}")

        self._add_progress_row(
            form,
            "vscode",
            "VS Code + TerosHDL (optional)",
        )
        self._set_vscode_row_enabled(False)
        root.addWidget(comps)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setPlaceholderText("Setup log…")
        root.addWidget(self.log)

        note = QLabel(
            "Prefer a path without spaces. After setup, restart this app (or log off/on) "
            "so other programs pick up the updated User PATH."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888; font-size: 11px;")
        root.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.start_btn = QPushButton("Start Setup")
        self.start_btn.clicked.connect(self._start)
        buttons.addWidget(self.start_btn)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)
        root.addLayout(buttons)

    def _add_progress_row(self, form: QFormLayout, key: str, title: str) -> None:
        label = QLabel(title)
        label.setStyleSheet("font-weight: bold;")
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFormat("%p%")
        status = QLabel("Waiting…")
        status.setStyleSheet("color: #888888; font-size: 11px;")
        cell = QVBoxLayout()
        cell.addWidget(bar)
        cell.addWidget(status)
        w = QWidget()
        w.setLayout(cell)
        form.addRow(label, w)
        self._bars[key] = bar
        self._status[key] = status
        # Keep label reference for enable/disable via form buddy
        w.setProperty("row_label", label)

    def _on_vscode_toggled(self, checked: bool) -> None:
        self._set_vscode_row_enabled(checked)

    def _set_vscode_row_enabled(self, enabled: bool) -> None:
        bar = self._bars.get("vscode")
        label = self._status.get("vscode")
        if not bar or not label:
            return
        bar.setEnabled(enabled)
        label.setEnabled(enabled)
        if enabled:
            label.setText("Waiting…")
            label.setStyleSheet("color: #888888; font-size: 11px;")
        else:
            label.setText("Skipped (unchecked)")
            label.setStyleSheet("color: #666666; font-size: 11px;")
            bar.setRange(0, 100)
            bar.setValue(0)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select toolchain install directory")
        if path:
            self.dir_edit.setText(path)

    def _append_log(self, text: str) -> None:
        self.log.append(text)

    def _start(self) -> None:
        target = self.dir_edit.text().strip()
        if not target:
            QMessageBox.warning(self, "Directory required", "Select an install directory first.")
            return
        if " " in target:
            reply = QMessageBox.question(
                self,
                "Path contains spaces",
                "OSS CAD Suite recommends an install path without spaces.\n\n"
                f"Continue with:\n{target}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "Invalid directory", str(e))
            return

        if self._worker and self._worker.isRunning():
            return

        install_vscode = self.vscode_check.isChecked()

        self.start_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        for key, bar in self._bars.items():
            if key == "vscode" and not install_vscode:
                continue
            bar.setRange(0, 100)
            bar.setValue(0)
            self._status[key].setText("Queued…")
            self._status[key].setStyleSheet("color: #FFB74D;")

        self._append_log(f"Install root: {target}")
        for comp in PINNED_COMPONENTS:
            self._append_log(f"• {comp.title} {comp.version}")
            self._append_log(f"  {comp.url}")
        if install_vscode:
            self._append_log("• VS Code (stable user setup) + TerosHDL extension")
        else:
            self._append_log("• VS Code / TerosHDL: skipped")

        self._worker = _AutoSetupWorker(target, install_vscode, self)
        self._worker.component_progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.finished_err.connect(self._on_err)
        self._worker.start()

    def _on_progress(self, key: str, cur: int, total: int, status: str) -> None:
        bar = self._bars.get(key)
        label = self._status.get(key)
        if not bar or not label:
            return
        if total and total > 0:
            bar.setRange(0, 100)
            bar.setValue(min(100, int(100 * cur / total)))
        else:
            bar.setRange(0, 0)
        label.setText(status)
        if status.startswith("FAILED"):
            label.setStyleSheet("color: #E57373;")
        elif (
            status in ("OK", "Extracted", "Download complete — extracting…")
            or "Configuring" in status
            or "installed" in status.lower()
            or "already" in status.lower()
        ):
            label.setStyleSheet("color: #81C784;")
        else:
            label.setStyleSheet("color: #FFB74D;")

    def _on_ok(self, resolved: dict, notes: List[str]) -> None:
        self._append_log("Downloads complete. Machine configuration:")
        for line in notes:
            self._append_log(line)
        for tool, path in resolved.items():
            self._append_log(f"Resolved {tool}: {path}")

        install_vscode = self.vscode_check.isChecked()
        for key, bar in self._bars.items():
            if key == "vscode" and not install_vscode:
                continue
            if bar.maximum() == 0:
                bar.setRange(0, 100)
            # Leave FAILED state alone if status already says FAILED
            status_text = self._status[key].text()
            if status_text.startswith("FAILED"):
                continue
            bar.setValue(100)
            self._status[key].setText("Done")
            self._status[key].setStyleSheet("color: #81C784;")

        self.start_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
        self.close_btn.setText("Close")
        try:
            self.close_btn.clicked.disconnect()
        except TypeError:
            pass
        self.close_btn.clicked.connect(self.accept)

        vscode_failed = any("VS Code / TerosHDL setup FAILED" in n for n in notes)
        msg = (
            "Toolchain is configured for this machine (User PATH + YOSYSHQ_ROOT).\n"
            "Restart GateMate Project Manager so Check Toolchain sees PATH tools.\n"
            "New projects will pick up these defaults automatically."
        )
        if install_vscode and vscode_failed:
            msg += "\n\nVS Code / TerosHDL step reported an error — see the setup log."
            QMessageBox.warning(self, "Auto-Setup finished with warnings", msg)
        else:
            QMessageBox.information(self, "Auto-Setup complete", msg)

    def _on_err(self, message: str) -> None:
        self._append_log(f"ERROR: {message}")
        self.start_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
        QMessageBox.critical(self, "Auto-Setup failed", message)

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Setup in progress",
                "Setup is still running. Close anyway?\n"
                "(Background work may leave partial files.)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        super().closeEvent(event)
