"""Place and Route settings dialog for nextpnr-himbaechel."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt5.QtSvg import QSvgWidget
except Exception:  # pragma: no cover - optional Qt module
    QSvgWidget = None

from .nextpnr_commands import DEFAULT_PNR_SETTINGS, NextPnRCommands


class PlaceAndRouteSettingsDialog(QDialog):
    """Configurable nextpnr place-and-route settings window."""

    PRESETS = {
        "Development": {
            "preset": "Development",
            "fpga_mode": "speed",
            "time_mode": "worst",
            "placer": "heap",
            "router": "router2",
            "seed_mode": "fixed",
            "fixed_seed": 1,
            "iterations": 1,
            "generate_report": True,
            "generate_bitstream": True,
        },
        "Timing Closure": {
            "preset": "Timing Closure",
            "fpga_mode": "speed",
            "time_mode": "worst",
            "placer": "heap",
            "router": "router2",
            "seed_mode": "multi",
            "first_seed": 1,
            "iterations": 20,
            "selection": "best_worst_slack",
            # parallel_jobs filled at apply-time from os.cpu_count()
            "generate_report": True,
            "generate_bitstream": True,
        },
        "Deep Optimization": {
            "preset": "Deep Optimization",
            "fpga_mode": "speed",
            "time_mode": "worst",
            "placer": "heap",
            "router": "router2",
            "seed_mode": "multi",
            "first_seed": 1,
            "iterations": 100,
            "selection": "best_worst_slack",
            # parallel_jobs filled at apply-time from os.cpu_count()
            "generate_report": True,
            "generate_bitstream": True,
        },
        "Custom": {
            "preset": "Custom",
        },
    }

    def __init__(self, parent=None, design_name: Optional[str] = None):
        super().__init__(parent)
        self.design_name = design_name or "design"
        self._updating = False
        self._pnr = NextPnRCommands()
        self.settings: Dict[str, Any] = self._pnr.load_pnr_settings()

        self.setWindowTitle(f"Place and Route Settings — {self.design_name}")
        self.setModal(True)
        self.resize(720, 820)
        self._build_ui()
        self._load_into_widgets(self.settings)
        self._update_seed_mode_enabled()
        self._update_force_die_visibility()
        self._refresh_command_preview()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        title = QLabel("PLACE AND ROUTE SETTINGS")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        design_label = QLabel(f"Design: {self.design_name}")
        design_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        root.addWidget(design_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)

        # Preset
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        for name in self.PRESETS:
            self.preset_combo.addItem(name, name)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_row.addWidget(self.preset_combo, 1)
        body_layout.addLayout(preset_row)

        # Device
        device_group = QGroupBox("Device")
        device_form = QFormLayout(device_group)
        self.device_combo = QComboBox()
        for d in ("CCGM1A1", "CCGM1A2", "CCGM1A4"):
            self.device_combo.addItem(d, d)
        self.device_combo.currentIndexChanged.connect(self._on_settings_changed)
        device_form.addRow("Device:", self.device_combo)

        self.fpga_mode_combo = QComboBox()
        for mode, label in (
            ("lowpower", "LOWPOWER"),
            ("economy", "ECONOMY"),
            ("speed", "SPEED"),
        ):
            self.fpga_mode_combo.addItem(label, mode)
        self.fpga_mode_combo.currentIndexChanged.connect(self._on_settings_changed)
        device_form.addRow("FPGA mode:", self.fpga_mode_combo)

        self.time_mode_combo = QComboBox()
        for mode, label in (
            ("best", "BEST - Analyze using best-case / fastest device delays"),
            ("typical", "TYPICAL - Analyze using nominal/typical delays"),
            ("worst", "WORST - Analyze using worst-case / slowest device delays"),
        ):
            self.time_mode_combo.addItem(label, mode)
        self.time_mode_combo.currentIndexChanged.connect(self._on_settings_changed)
        device_form.addRow("Timing model:", self.time_mode_combo)
        body_layout.addWidget(device_group)

        # Constraints (.ccf) — keep existing project workflow
        ccf_group = QGroupBox("Pin constraints (.ccf)")
        ccf_layout = QVBoxLayout(ccf_group)
        self.constraints_combo = QComboBox()
        self._populate_constraints()
        self.constraints_combo.currentIndexChanged.connect(self._on_settings_changed)
        ccf_layout.addWidget(self.constraints_combo)
        body_layout.addWidget(ccf_group)

        # Timing constraints
        timing_group = QGroupBox("Timing constraints")
        timing_form = QFormLayout(timing_group)

        sdc_row = QHBoxLayout()
        self.sdc_edit = QLineEdit()
        self.sdc_edit.setPlaceholderText("optional design.sdc")
        self.sdc_edit.textChanged.connect(self._on_settings_changed)
        browse_sdc = QPushButton("Browse...")
        browse_sdc.clicked.connect(self._browse_sdc)
        sdc_row.addWidget(self.sdc_edit, 1)
        sdc_row.addWidget(browse_sdc)
        timing_form.addRow("SDC file:", sdc_row)

        freq_row = QHBoxLayout()
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(0.0, 10000.0)
        self.freq_spin.setDecimals(2)
        self.freq_spin.setSuffix(" MHz")
        self.freq_spin.valueChanged.connect(self._on_settings_changed)
        self.use_freq_check = QCheckBox("Use fallback / single-clock target frequency")
        self.use_freq_check.setChecked(True)
        self.use_freq_check.stateChanged.connect(self._on_settings_changed)
        freq_row.addWidget(self.freq_spin)
        freq_row.addWidget(self.use_freq_check)
        timing_form.addRow("Fallback frequency:", freq_row)

        self.allow_fail_check = QCheckBox("Allow timing failure")
        self.allow_fail_check.stateChanged.connect(self._on_settings_changed)
        timing_form.addRow("", self.allow_fail_check)

        self.timing_warning = QLabel("")
        self.timing_warning.setWordWrap(True)
        self.timing_warning.setStyleSheet("color: #FF9800;")
        timing_form.addRow(self.timing_warning)
        body_layout.addWidget(timing_group)

        # Placement
        place_group = QGroupBox("Placement")
        place_form = QFormLayout(place_group)
        self.placer_combo = QComboBox()
        self.placer_combo.addItem("HEAP", "heap")
        self.placer_combo.currentIndexChanged.connect(self._on_settings_changed)
        place_form.addRow("Placer:", self.placer_combo)

        seed_mode_box = QHBoxLayout()
        self.seed_fixed_radio = QRadioButton("Fixed")
        self.seed_multi_radio = QRadioButton("Multi-seed search")
        self.seed_mode_group = QButtonGroup(self)
        self.seed_mode_group.addButton(self.seed_fixed_radio)
        self.seed_mode_group.addButton(self.seed_multi_radio)
        self.seed_fixed_radio.toggled.connect(self._on_seed_mode_toggled)
        seed_mode_box.addWidget(self.seed_fixed_radio)
        seed_mode_box.addWidget(self.seed_multi_radio)
        place_form.addRow("Seed mode:", seed_mode_box)

        self.fixed_seed_spin = QSpinBox()
        self.fixed_seed_spin.setRange(0, 2_147_483_647)
        self.fixed_seed_spin.valueChanged.connect(self._on_settings_changed)
        place_form.addRow("Seed:", self.fixed_seed_spin)
        body_layout.addWidget(place_group)

        # Multi-seed
        self.multi_group = QGroupBox("Multi-seed search")
        multi_form = QFormLayout(self.multi_group)
        self.iterations_spin = QSpinBox()
        self.iterations_spin.setRange(1, 10000)
        self.iterations_spin.valueChanged.connect(self._on_settings_changed)
        multi_form.addRow("Iterations:", self.iterations_spin)

        self.first_seed_spin = QSpinBox()
        self.first_seed_spin.setRange(0, 2_147_483_647)
        self.first_seed_spin.valueChanged.connect(self._on_settings_changed)
        multi_form.addRow("First seed:", self.first_seed_spin)

        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 64)
        cpu_cores = os.cpu_count() or 1
        parallel_tip = (
            f"Number of concurrent nextpnr processes for multi-seed search.\n"
            f"This machine reports {cpu_cores} CPU core(s).\n"
            f"1 = sequential (live preview follows each seed).\n"
            f">1 = parallel workers (preview shows the current best seed).\n"
            f"Disk and RAM often limit useful parallelism before core count does."
        )
        self.parallel_spin.setToolTip(parallel_tip)
        self.parallel_spin.valueChanged.connect(self._on_settings_changed)
        parallel_row = QWidget()
        parallel_layout = QHBoxLayout(parallel_row)
        parallel_layout.setContentsMargins(0, 0, 0, 0)
        parallel_layout.addWidget(self.parallel_spin)
        parallel_note = QLabel(f"Detected cores: {cpu_cores}")
        parallel_note.setStyleSheet("color: #AAAAAA;")
        parallel_note.setToolTip(parallel_tip)
        parallel_layout.addWidget(parallel_note)
        parallel_layout.addStretch(1)
        multi_form.addRow("Parallel jobs:", parallel_row)

        self.selection_combo = QComboBox()
        self.selection_combo.addItem("Best worst-case timing", "best_worst_slack")
        self.selection_combo.addItem("Best Fmax", "best_fmax")
        self.selection_combo.addItem("Lowest wire length", "lowest_wirelength")
        self.selection_combo.currentIndexChanged.connect(self._on_settings_changed)
        multi_form.addRow("Selection:", self.selection_combo)

        self.stop_when_met_check = QCheckBox("Stop once timing constraints are met")
        self.stop_when_met_check.stateChanged.connect(self._on_settings_changed)
        multi_form.addRow("", self.stop_when_met_check)
        body_layout.addWidget(self.multi_group)

        # Routing
        route_group = QGroupBox("Routing")
        route_form = QFormLayout(route_group)
        self.router_combo = QComboBox()
        self.router_combo.addItem("ROUTER2 (recommended)", "router2")
        self.router_combo.currentIndexChanged.connect(self._on_settings_changed)
        route_form.addRow("Router:", self.router_combo)
        body_layout.addWidget(route_group)

        # Reports
        reports_group = QGroupBox("Reports")
        reports_layout = QVBoxLayout(reports_group)
        self.report_check = QCheckBox("Generate timing/utilization JSON")
        self.keep_log_check = QCheckBox("Keep P&R log")
        self.sdf_check = QCheckBox("Generate SDF")
        self.placed_svg_check = QCheckBox("Generate placed SVG")
        self.routed_svg_check = QCheckBox("Generate routed SVG")
        self.gui_check = QCheckBox("Open GUI after routing")
        self.bitstream_check = QCheckBox("Generate bitstream (gmpack) after P&R")
        for w in (
            self.report_check,
            self.keep_log_check,
            self.sdf_check,
            self.placed_svg_check,
            self.routed_svg_check,
            self.gui_check,
            self.bitstream_check,
        ):
            w.stateChanged.connect(self._on_settings_changed)
            reports_layout.addWidget(w)
        body_layout.addWidget(reports_group)

        # Advanced expander
        self.advanced_toggle = QPushButton("Advanced ▸")
        self.advanced_toggle.setFlat(True)
        self.advanced_toggle.setStyleSheet("text-align: left; color: #64B5F6;")
        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        body_layout.addWidget(self.advanced_toggle)

        self.advanced_frame = QFrame()
        self.advanced_frame.setVisible(False)
        adv_layout = QVBoxLayout(self.advanced_frame)

        warn = QLabel(
            "Changing advanced placer/router parameters can significantly alter timing "
            "and routability. Leave at defaults unless benchmarking demonstrates an improvement."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #FF9800;")
        adv_layout.addWidget(warn)

        # Advanced placer choices
        adv_place = QGroupBox("Placement tuning")
        adv_place_form = QFormLayout(adv_place)
        self.adv_placer_combo = QComboBox()
        for value, label in (("heap", "HEAP"), ("sa", "SA"), ("static", "STATIC")):
            self.adv_placer_combo.addItem(label, value)
        self.adv_placer_combo.currentIndexChanged.connect(self._on_adv_placer_changed)
        adv_place_form.addRow("Placer algorithm:", self.adv_placer_combo)

        self.heap_alpha_edit = QLineEdit()
        self.heap_alpha_edit.setPlaceholderText("default")
        self.heap_beta_edit = QLineEdit()
        self.heap_beta_edit.setPlaceholderText("default")
        self.heap_critexp_edit = QLineEdit()
        self.heap_critexp_edit.setPlaceholderText("default")
        self.heap_timingweight_edit = QLineEdit()
        self.heap_timingweight_edit.setPlaceholderText("default")
        for edit in (
            self.heap_alpha_edit,
            self.heap_beta_edit,
            self.heap_critexp_edit,
            self.heap_timingweight_edit,
        ):
            edit.textChanged.connect(self._on_settings_changed)
        adv_place_form.addRow("Heap alpha:", self.heap_alpha_edit)
        adv_place_form.addRow("Heap beta:", self.heap_beta_edit)
        adv_place_form.addRow("Heap criticality exp:", self.heap_critexp_edit)
        adv_place_form.addRow("Heap timing weight:", self.heap_timingweight_edit)
        adv_layout.addWidget(adv_place)

        adv_route = QGroupBox("Router tuning")
        adv_route_layout = QVBoxLayout(adv_route)
        self.adv_router_combo = QComboBox()
        for value, label in (
            ("router2", "ROUTER2 (recommended)"),
            ("router1", "ROUTER1"),
            ("default", "DEFAULT"),
        ):
            self.adv_router_combo.addItem(label, value)
        self.adv_router_combo.currentIndexChanged.connect(self._on_adv_router_changed)
        adv_route_layout.addWidget(QLabel("Router algorithm:"))
        adv_route_layout.addWidget(self.adv_router_combo)
        self.tmg_ripup_check = QCheckBox("Timing-driven ripup")
        self.alt_weights_check = QCheckBox("Alternate router2 weights")
        self.tmg_ripup_check.stateChanged.connect(self._on_settings_changed)
        self.alt_weights_check.stateChanged.connect(self._on_settings_changed)
        adv_route_layout.addWidget(self.tmg_ripup_check)
        adv_route_layout.addWidget(self.alt_weights_check)
        adv_layout.addWidget(adv_route)

        arch = QGroupBox("Architecture")
        arch_form = QFormLayout(arch)
        self.clock_strategy_combo = QComboBox()
        for value, label in (
            ("auto", "DEFAULT/AUTO"),
            ("mirror", "mirror"),
            ("full", "full"),
            ("clk1", "clk1"),
        ):
            self.clock_strategy_combo.addItem(label, value)
        self.clock_strategy_combo.currentIndexChanged.connect(self._on_settings_changed)
        arch_form.addRow("Clock strategy:", self.clock_strategy_combo)
        self.no_cpe_cp_check = QCheckBox("Disable CPE CP pass-through")
        self.no_bridges_check = QCheckBox("Disable bridges")
        self.force_die_check = QCheckBox("force_die (CCGM1A2 only)")
        for w in (self.no_cpe_cp_check, self.no_bridges_check, self.force_die_check):
            w.stateChanged.connect(self._on_settings_changed)
            arch_form.addRow("", w)
        adv_layout.addWidget(arch)

        diag = QGroupBox("Diagnostics")
        diag_layout = QVBoxLayout(diag)
        self.detailed_timing_check = QCheckBox("Detailed timing report")
        self.verbose_check = QCheckBox("Verbose")
        self.debug_check = QCheckBox("Debug")
        for w in (self.detailed_timing_check, self.verbose_check, self.debug_check):
            w.stateChanged.connect(self._on_settings_changed)
            diag_layout.addWidget(w)
        adv_layout.addWidget(diag)

        body_layout.addWidget(self.advanced_frame)

        # Command preview
        preview_group = QGroupBox("Command Preview")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_edit = QTextEdit()
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setMinimumHeight(110)
        self.preview_edit.setFont(QFont("Consolas", 9))
        preview_layout.addWidget(self.preview_edit)
        body_layout.addWidget(preview_group)

        body_layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # Buttons
        buttons = QHBoxLayout()
        reset_btn = QPushButton("Reset Recommended")
        reset_btn.clicked.connect(self._reset_recommended)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        run_btn = QPushButton("Run P&R")
        run_btn.setDefault(True)
        run_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }"
        )
        run_btn.clicked.connect(self._accept_and_run)
        buttons.addWidget(reset_btn)
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(run_btn)
        root.addLayout(buttons)

    def _populate_constraints(self) -> None:
        self.constraints_combo.clear()
        available = []
        try:
            available = self._pnr.list_available_constraint_files()
        except Exception as e:
            logging.warning(f"Could not list constraint files: {e}")

        preview = "none"
        try:
            path, reason, _ = self._pnr.resolve_constraint_file(design_name=self.design_name)
            if path:
                preview = os.path.basename(path)
            elif reason:
                preview = reason
        except Exception:
            pass

        self.constraints_combo.addItem(f"Use Default (Auto-detect: {preview})", "default")
        design_ccf = f"{self.design_name}.ccf"
        for name in available:
            label = name
            if name == design_ccf:
                label = f"{name} (recommended for this design)"
            self.constraints_combo.addItem(label, name)
            if name == design_ccf:
                self.constraints_combo.setCurrentIndex(self.constraints_combo.count() - 1)

        if not available:
            self.constraints_combo.addItem("No constraint files found", "none")

    def _toggle_advanced(self) -> None:
        visible = not self.advanced_frame.isVisible()
        self.advanced_frame.setVisible(visible)
        self.advanced_toggle.setText("Advanced ▾" if visible else "Advanced ▸")

    def _browse_sdc(self) -> None:
        start = self.sdc_edit.text().strip() or self._pnr.constraints_dir
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SDC timing constraints",
            start,
            "SDC files (*.sdc);;All files (*.*)",
        )
        if path:
            self.sdc_edit.setText(path)

    def _set_combo_data(self, combo: QComboBox, value: Any) -> None:
        idx = combo.findData(value)
        if idx < 0 and value is not None:
            idx = combo.findData(str(value).lower())
        if idx < 0 and value is not None:
            idx = combo.findText(str(value), Qt.MatchFixedString)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _load_into_widgets(self, settings: Dict[str, Any]) -> None:
        self._updating = True
        try:
            preset = settings.get("preset", "Development")
            self._set_combo_data(self.preset_combo, preset)
            if self.preset_combo.currentData() is None:
                self.preset_combo.setCurrentText(str(preset))

            self._set_combo_data(self.device_combo, settings.get("device", "CCGM1A1"))
            self._set_combo_data(self.fpga_mode_combo, settings.get("fpga_mode", "speed"))
            self._set_combo_data(self.time_mode_combo, settings.get("time_mode", "worst"))

            self.sdc_edit.setText(settings.get("sdc_path") or "")
            try:
                self.freq_spin.setValue(float(settings.get("fallback_frequency_mhz") or 100.0))
            except (TypeError, ValueError):
                self.freq_spin.setValue(100.0)
            self.use_freq_check.setChecked(bool(settings.get("use_fallback_frequency", True)))
            self.allow_fail_check.setChecked(bool(settings.get("allow_timing_failure", False)))

            placer = (settings.get("placer") or "heap").lower()
            self._set_combo_data(self.placer_combo, placer if placer == "heap" else "heap")
            self._set_combo_data(self.adv_placer_combo, placer)

            if (settings.get("seed_mode") or "fixed").lower() == "multi":
                self.seed_multi_radio.setChecked(True)
            else:
                self.seed_fixed_radio.setChecked(True)

            self.fixed_seed_spin.setValue(int(settings.get("fixed_seed", 1) or 1))
            self.iterations_spin.setValue(int(settings.get("iterations", 20) or 20))
            self.first_seed_spin.setValue(int(settings.get("first_seed", 1) or 1))
            self.parallel_spin.setValue(int(settings.get("parallel_jobs", 1) or 1))
            self._set_combo_data(
                self.selection_combo, settings.get("selection", "best_worst_slack")
            )
            self.stop_when_met_check.setChecked(bool(settings.get("stop_when_timing_met", False)))

            router = (settings.get("router") or "router2").lower()
            self._set_combo_data(self.router_combo, "router2")
            self._set_combo_data(self.adv_router_combo, router)

            self.report_check.setChecked(bool(settings.get("generate_report", True)))
            self.keep_log_check.setChecked(bool(settings.get("keep_log", True)))
            self.sdf_check.setChecked(bool(settings.get("generate_sdf", False)))
            self.placed_svg_check.setChecked(bool(settings.get("generate_placed_svg", False)))
            self.routed_svg_check.setChecked(bool(settings.get("generate_routed_svg", False)))
            self.gui_check.setChecked(bool(settings.get("open_gui", False)))
            self.bitstream_check.setChecked(bool(settings.get("generate_bitstream", True)))

            self.heap_alpha_edit.setText(str(settings.get("heap_alpha") or ""))
            self.heap_beta_edit.setText(str(settings.get("heap_beta") or ""))
            self.heap_critexp_edit.setText(str(settings.get("heap_critexp") or ""))
            self.heap_timingweight_edit.setText(str(settings.get("heap_timingweight") or ""))
            self.tmg_ripup_check.setChecked(bool(settings.get("timing_driven_ripup", False)))
            self.alt_weights_check.setChecked(bool(settings.get("router2_alt_weights", False)))
            self._set_combo_data(
                self.clock_strategy_combo, settings.get("clock_strategy", "auto")
            )
            self.no_cpe_cp_check.setChecked(bool(settings.get("no_cpe_cp", False)))
            self.no_bridges_check.setChecked(bool(settings.get("no_bridges", False)))
            self.force_die_check.setChecked(bool(settings.get("force_die", False)))
            self.detailed_timing_check.setChecked(
                bool(settings.get("detailed_timing_report", False))
            )
            self.verbose_check.setChecked(bool(settings.get("verbose", False)))
            self.debug_check.setChecked(bool(settings.get("debug", False)))
        finally:
            self._updating = False

    def collect_settings(self) -> Dict[str, Any]:
        """Collect current widget values into a settings dict."""
        placer = self.adv_placer_combo.currentData() or self.placer_combo.currentData() or "heap"
        router = self.adv_router_combo.currentData() or self.router_combo.currentData() or "router2"
        seed_mode = "multi" if self.seed_multi_radio.isChecked() else "fixed"

        settings = dict(DEFAULT_PNR_SETTINGS)
        settings.update(
            {
                "preset": self.preset_combo.currentData() or self.preset_combo.currentText(),
                "device": self.device_combo.currentData() or "CCGM1A1",
                "fpga_mode": self.fpga_mode_combo.currentData() or "speed",
                "time_mode": self.time_mode_combo.currentData() or "worst",
                "sdc_path": self.sdc_edit.text().strip(),
                "fallback_frequency_mhz": float(self.freq_spin.value()),
                "use_fallback_frequency": self.use_freq_check.isChecked(),
                "allow_timing_failure": self.allow_fail_check.isChecked(),
                "placer": placer,
                "seed_mode": seed_mode,
                "fixed_seed": int(self.fixed_seed_spin.value()),
                "iterations": int(self.iterations_spin.value()),
                "first_seed": int(self.first_seed_spin.value()),
                "parallel_jobs": int(self.parallel_spin.value()),
                "selection": self.selection_combo.currentData() or "best_worst_slack",
                "stop_when_timing_met": self.stop_when_met_check.isChecked(),
                "router": router,
                "generate_report": self.report_check.isChecked(),
                "keep_log": self.keep_log_check.isChecked(),
                "generate_sdf": self.sdf_check.isChecked(),
                "generate_placed_svg": self.placed_svg_check.isChecked(),
                "generate_routed_svg": self.routed_svg_check.isChecked(),
                "open_gui": self.gui_check.isChecked(),
                "generate_bitstream": self.bitstream_check.isChecked(),
                "heap_alpha": self.heap_alpha_edit.text().strip(),
                "heap_beta": self.heap_beta_edit.text().strip(),
                "heap_critexp": self.heap_critexp_edit.text().strip(),
                "heap_timingweight": self.heap_timingweight_edit.text().strip(),
                "timing_driven_ripup": self.tmg_ripup_check.isChecked(),
                "router2_alt_weights": self.alt_weights_check.isChecked(),
                "clock_strategy": self.clock_strategy_combo.currentData() or "auto",
                "no_cpe_cp": self.no_cpe_cp_check.isChecked(),
                "no_bridges": self.no_bridges_check.isChecked(),
                "force_die": self.force_die_check.isChecked(),
                "detailed_timing_report": self.detailed_timing_check.isChecked(),
                "verbose": self.verbose_check.isChecked(),
                "debug": self.debug_check.isChecked(),
                # Legacy / GUI compatibility keys
                "strategy": "balanced",
                "design_name": self.design_name,
                "constraint_file": self.constraints_combo.currentData(),
                "run_timing_analysis": False,
                "generate_sim_netlist": False,
            }
        )
        return settings

    def get_implementation_params(self) -> Dict[str, Any]:
        """Compatibility alias used by existing GUI callers."""
        return self.collect_settings()

    def _on_preset_changed(self) -> None:
        if self._updating:
            return
        name = self.preset_combo.currentData() or self.preset_combo.currentText()
        if name == "Custom":
            return
        preset = dict(DEFAULT_PNR_SETTINGS)
        preset.update(self.PRESETS.get(name, {}))
        # Timing / deep multi-seed presets: use all detected cores by default
        if name in ("Timing Closure", "Deep Optimization"):
            cores = max(1, int(os.cpu_count() or 1))
            # Keep within the Parallel jobs spinbox range
            preset["parallel_jobs"] = min(64, cores)
        # Keep device / SDC / constraint choices
        current = self.collect_settings()
        for keep in ("device", "sdc_path", "fallback_frequency_mhz", "use_fallback_frequency"):
            preset[keep] = current.get(keep, preset.get(keep))
        self._load_into_widgets(preset)
        self._update_seed_mode_enabled()
        self._update_force_die_visibility()
        self._refresh_command_preview()

    def _on_seed_mode_toggled(self, *_args) -> None:
        self._update_seed_mode_enabled()
        self._mark_custom_preset()
        self._refresh_command_preview()

    def _update_seed_mode_enabled(self) -> None:
        multi = self.seed_multi_radio.isChecked()
        self.fixed_seed_spin.setEnabled(not multi)
        self.multi_group.setEnabled(multi)

    def _update_force_die_visibility(self) -> None:
        device = self.device_combo.currentData() or ""
        self.force_die_check.setEnabled(str(device).upper() == "CCGM1A2")
        if str(device).upper() != "CCGM1A2":
            self.force_die_check.setChecked(False)

    def _on_adv_placer_changed(self) -> None:
        if self._updating:
            return
        value = self.adv_placer_combo.currentData()
        if value == "heap":
            self._set_combo_data(self.placer_combo, "heap")
        self._mark_custom_preset()
        self._refresh_command_preview()

    def _on_adv_router_changed(self) -> None:
        if self._updating:
            return
        value = self.adv_router_combo.currentData()
        if value == "router2":
            self._set_combo_data(self.router_combo, "router2")
        self._mark_custom_preset()
        self._refresh_command_preview()

    def _mark_custom_preset(self) -> None:
        if self._updating:
            return
        if (self.preset_combo.currentData() or "") != "Custom":
            self._updating = True
            try:
                idx = self.preset_combo.findData("Custom")
                if idx >= 0:
                    self.preset_combo.setCurrentIndex(idx)
            finally:
                self._updating = False

    def _on_settings_changed(self, *_args) -> None:
        if self._updating:
            return
        self._mark_custom_preset()
        self._update_force_die_visibility()
        self._refresh_command_preview()

    def _reset_recommended(self) -> None:
        settings = dict(DEFAULT_PNR_SETTINGS)
        settings["preset"] = "Development"
        self._load_into_widgets(settings)
        self._set_combo_data(self.preset_combo, "Development")
        self._update_seed_mode_enabled()
        self._update_force_die_visibility()
        self._refresh_command_preview()

    def _resolve_preview_paths(self, settings: Dict[str, Any]):
        netlist = os.path.join(self._pnr.synth_dir, f"{self.design_name}_synth.json")
        if not os.path.exists(netlist):
            netlist = f"{self.design_name}_synth.json"

        constraint = settings.get("constraint_file")
        if constraint and constraint not in ("default", "none"):
            ccf = (
                constraint
                if os.path.isabs(constraint)
                else os.path.join(self._pnr.constraints_dir, constraint)
            )
        else:
            try:
                ccf, _, _ = self._pnr.resolve_constraint_file(design_name=self.design_name)
            except Exception:
                ccf = None
            if not ccf:
                ccf = os.path.join(self._pnr.constraints_dir, f"{self.design_name}.ccf")

        if (settings.get("seed_mode") or "fixed") == "multi":
            seed = int(settings.get("first_seed", 1) or 1)
            out = os.path.join(
                self._pnr.work_dir, f"{self.design_name}_impl_seed_{seed:03d}.txt"
            )
            report = os.path.join(
                self._pnr.timing_dir, f"{self.design_name}_report_seed_{seed:03d}.json"
            )
        else:
            seed = int(settings.get("fixed_seed", 1) or 1)
            out = os.path.join(self._pnr.work_dir, f"{self.design_name}_impl.txt")
            report = os.path.join(self._pnr.timing_dir, f"{self.design_name}_report.json")
        return netlist, ccf, out, report, seed

    def _refresh_command_preview(self) -> None:
        settings = self.collect_settings()
        sdc = (settings.get("sdc_path") or "").strip()
        use_freq = settings.get("use_fallback_frequency") and float(
            settings.get("fallback_frequency_mhz") or 0
        ) > 0
        if not sdc and not use_freq:
            self.timing_warning.setText(
                "⚠️ No timing constraints supplied. P&R can complete, but timing "
                "closure cannot be meaningfully verified."
            )
        elif sdc and not os.path.exists(sdc):
            self.timing_warning.setText(f"⚠️ SDC file not found: {sdc}")
        else:
            self.timing_warning.setText("")

        netlist, ccf, out, report, seed = self._resolve_preview_paths(settings)
        try:
            cmd = self._pnr.build_nextpnr_command(
                design_name=self.design_name,
                netlist_file=netlist,
                constraint_file=ccf,
                output_file=out,
                settings=settings,
                seed=seed,
                report_file=report if settings.get("generate_report") else None,
            )
            text = self._pnr.format_command_preview(cmd)
            if (settings.get("seed_mode") or "fixed") == "multi":
                iters = int(settings.get("iterations", 20) or 20)
                first = int(settings.get("first_seed", 1) or 1)
                text = (
                    f"# Multi-seed search: seeds {first}..{first + iters - 1}\n"
                    f"# Preview shows first seed only\n"
                    f"{text}"
                )
            self.preview_edit.setPlainText(text)
        except Exception as e:
            self.preview_edit.setPlainText(f"(preview unavailable: {e})")

    def _accept_and_run(self) -> None:
        settings = self.collect_settings()
        constraint = settings.get("constraint_file")
        if constraint == "none":
            QMessageBox.warning(
                self,
                "Constraint file required",
                "No pin constraint (.ccf) file is available. Create one before running P&R.",
            )
            return

        sdc = (settings.get("sdc_path") or "").strip()
        use_freq = settings.get("use_fallback_frequency") and float(
            settings.get("fallback_frequency_mhz") or 0
        ) > 0
        if not sdc and not use_freq:
            reply = QMessageBox.warning(
                self,
                "No timing constraints",
                "No timing constraint file or target frequency is specified.\n"
                "P&R may complete, but meaningful timing closure cannot be verified.\n\n"
                "Continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        try:
            self._pnr.save_pnr_settings(settings)
        except Exception as e:
            logging.warning(f"Could not persist P&R settings: {e}")

        self.settings = settings
        self.accept()


class MultiSeedProgressDialog(QDialog):
    """Live multi-seed P&R progress with side-by-side placed/routed SVG previews."""

    def __init__(self, parent=None, design_name: str = "", total_seeds: int = 1):
        super().__init__(parent)
        self.design_name = design_name or "design"
        self.total_seeds = max(1, int(total_seeds or 1))
        self._finished = False
        self._current_seed = 0
        self._elapsed_seconds = 0
        self._run_active = False

        self.setWindowTitle(f"Multi-seed Place & Route — {self.design_name}")
        self.setModal(False)
        self.resize(1100, 780)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        root = QVBoxLayout(self)

        self.title_label = QLabel(f"Design: {self.design_name}")
        self.title_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        root.addWidget(self.title_label)

        # Single progress bar: seed count + elapsed runtime
        self.progress = QProgressBar()
        self.progress.setRange(0, self.total_seeds)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(28)
        self.progress.setFormat("Seed %v / %m — elapsed 00:00")
        root.addWidget(self.progress)

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self.timing_group = QGroupBox("Current seed timing (from report JSON)")
        timing_layout = QVBoxLayout(self.timing_group)
        timing_form = QFormLayout()
        self.status_value = QLabel("—")
        self.slack_value = QLabel("—")
        self.fmax_value = QLabel("—")
        self.best_value = QLabel("—")
        self.report_path_value = QLabel("—")
        self.report_path_value.setWordWrap(True)
        self.report_path_value.setStyleSheet("color: #AAAAAA; font-size: 11px;")
        timing_form.addRow("Status:", self.status_value)
        timing_form.addRow("Worst slack:", self.slack_value)
        timing_form.addRow("Limiting Fmax:", self.fmax_value)
        timing_form.addRow("Best so far:", self.best_value)
        timing_form.addRow("Report:", self.report_path_value)
        timing_layout.addLayout(timing_form)

        self.report_summary = QTextEdit()
        self.report_summary.setReadOnly(True)
        self.report_summary.setMaximumHeight(110)
        self.report_summary.setFont(QFont("Consolas", 9))
        self.report_summary.setPlaceholderText("Timing / utilization fields from *_report_seed_XXX.json")
        timing_layout.addWidget(self.report_summary)
        root.addWidget(self.timing_group)

        # Side-by-side placed vs routed SVG
        svg_group = QGroupBox("FPGA layout preview")
        svg_root = QVBoxLayout(svg_group)
        svg_split = QSplitter(Qt.Horizontal)

        placed_panel = QWidget()
        placed_layout = QVBoxLayout(placed_panel)
        placed_layout.setContentsMargins(0, 0, 0, 0)
        placed_title = QLabel("Placed (_placed.svg)")
        placed_title.setAlignment(Qt.AlignCenter)
        placed_title.setStyleSheet("font-weight: bold; color: #90CAF9;")
        placed_layout.addWidget(placed_title)
        placed_help = QLabel(
            "Physical positions of logic resources on the FPGA (before routing)."
        )
        placed_help.setWordWrap(True)
        placed_help.setAlignment(Qt.AlignCenter)
        placed_help.setStyleSheet("color: #AAAAAA; font-size: 10px;")
        placed_layout.addWidget(placed_help)
        self.placed_path_label = QLabel("Waiting…")
        self.placed_path_label.setWordWrap(True)
        self.placed_path_label.setStyleSheet("color: #888; font-size: 10px;")
        placed_layout.addWidget(self.placed_path_label)

        routed_panel = QWidget()
        routed_layout = QVBoxLayout(routed_panel)
        routed_layout.setContentsMargins(0, 0, 0, 0)
        routed_title = QLabel("Routed (_routed.svg)")
        routed_title.setAlignment(Qt.AlignCenter)
        routed_title.setStyleSheet("font-weight: bold; color: #A5D6A7;")
        routed_layout.addWidget(routed_title)
        routed_help = QLabel(
            "Same placement, plus the wiring between logic resources."
        )
        routed_help.setWordWrap(True)
        routed_help.setAlignment(Qt.AlignCenter)
        routed_help.setStyleSheet("color: #AAAAAA; font-size: 10px;")
        routed_layout.addWidget(routed_help)
        self.routed_path_label = QLabel("Waiting…")
        self.routed_path_label.setWordWrap(True)
        self.routed_path_label.setStyleSheet("color: #888; font-size: 10px;")
        routed_layout.addWidget(self.routed_path_label)

        if QSvgWidget is not None:
            self.placed_svg_widget = QSvgWidget()
            self.placed_svg_widget.setMinimumHeight(280)
            placed_layout.addWidget(self.placed_svg_widget, 1)
            self.routed_svg_widget = QSvgWidget()
            self.routed_svg_widget.setMinimumHeight(280)
            routed_layout.addWidget(self.routed_svg_widget, 1)
            self.placed_fallback = None
            self.routed_fallback = None
        else:
            self.placed_svg_widget = None
            self.routed_svg_widget = None
            self.placed_fallback = QLabel("QtSvg not available")
            self.placed_fallback.setAlignment(Qt.AlignCenter)
            self.placed_fallback.setMinimumHeight(200)
            self.placed_fallback.setStyleSheet("background:#1e1e1e; color:#ccc; border:1px solid #444;")
            placed_layout.addWidget(self.placed_fallback, 1)
            self.routed_fallback = QLabel("QtSvg not available")
            self.routed_fallback.setAlignment(Qt.AlignCenter)
            self.routed_fallback.setMinimumHeight(200)
            self.routed_fallback.setStyleSheet("background:#1e1e1e; color:#ccc; border:1px solid #444;")
            routed_layout.addWidget(self.routed_fallback, 1)

        svg_split.addWidget(placed_panel)
        svg_split.addWidget(routed_panel)
        svg_split.setStretchFactor(0, 1)
        svg_split.setStretchFactor(1, 1)
        svg_root.addWidget(svg_split)
        root.addWidget(svg_group, 1)

        table_group = QGroupBox("Seed results")
        table_layout = QVBoxLayout(table_group)
        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(
            ["Seed", "Worst Slack", "Fmax", "Status", "Best"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        table_layout.addWidget(self.results_table)
        root.addWidget(table_group)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.close_btn)
        root.addLayout(buttons)

        self._refresh_progress_format()

    def _format_elapsed(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        mins, secs = divmod(seconds, 60)
        hours, mins = divmod(mins, 60)
        if hours:
            return f"{hours:d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def _refresh_progress_format(self) -> None:
        elapsed = self._format_elapsed(self._elapsed_seconds)
        if self._finished:
            self.progress.setFormat(
                f"Complete — Seed %v / %m — elapsed {elapsed}"
            )
        elif self._run_active:
            self.progress.setFormat(
                f"Seed %v / %m — elapsed {elapsed} (running…)"
            )
        else:
            self.progress.setFormat(f"Seed %v / %m — elapsed {elapsed}")

    def _tick_elapsed(self) -> None:
        if not self._run_active or self._finished:
            return
        self._elapsed_seconds += 1
        self._refresh_progress_format()

    def _start_elapsed_timer(self) -> None:
        self._elapsed_seconds = 0
        self._run_active = True
        self._finished = False
        self._refresh_progress_format()
        if not self._elapsed_timer.isActive():
            self._elapsed_timer.start()

    def _stop_elapsed_timer(self) -> None:
        self._run_active = False
        self._elapsed_timer.stop()
        self._refresh_progress_format()

    def handle_progress(self, info: Dict[str, Any]) -> None:
        """Handle a progress event dict from NextPnRCommands."""
        if not isinstance(info, dict):
            return
        event = info.get("event")

        if event == "multi_seed_start":
            self.total_seeds = max(1, int(info.get("total") or self.total_seeds))
            self.progress.setRange(0, self.total_seeds)
            self.progress.setValue(0)
            self.close_btn.setEnabled(False)
            self._start_elapsed_timer()
            self.status_value.setText("STARTING")
            self.status_value.setStyleSheet("color: #FFB74D; font-weight: bold;")
            self.timing_group.setTitle("Current seed timing (from report JSON)")
            self.report_path_value.setText("—")
            self.slack_value.setText("—")
            self.fmax_value.setText("—")
            self.best_value.setText("—")
            self.report_summary.clear()
            self.placed_path_label.setText("Waiting…")
            self.routed_path_label.setText("Waiting…")
            return

        if event == "seed_start":
            index = int(info.get("index") or 0)
            total = int(info.get("total") or self.total_seeds)
            seed = info.get("seed")
            self._current_seed = seed
            self.total_seeds = max(1, total)
            self.progress.setRange(0, self.total_seeds)
            # Show the seed currently running as the progress value
            self.progress.setValue(max(0, index))
            self._run_active = True
            self._refresh_progress_format()
            parallel_jobs = int(info.get("parallel_jobs") or 1)
            if info.get("show_best") and parallel_jobs > 1:
                workers = info.get("active_workers") or parallel_jobs
                self.status_value.setText(
                    f"RUNNING {workers} parallel jobs (showing best when available)"
                )
            else:
                self.status_value.setText(f"RUNNING seed {seed}")
            self.status_value.setStyleSheet("color: #FFB74D; font-weight: bold;")
            return

        if event == "seed_done":
            index = int(info.get("index") or 0)
            total = int(info.get("total") or self.total_seeds)
            seed = info.get("seed")
            status = info.get("status") or ("PASS" if info.get("success") else "FAIL")
            self.total_seeds = max(1, total)
            self.progress.setRange(0, self.total_seeds)
            self.progress.setValue(index)
            self._refresh_progress_format()

            show_best = bool(info.get("show_best"))
            display_seed = info.get("display_seed")
            if show_best and display_seed is not None:
                self.status_value.setText(
                    f"{status} seed {seed} — displaying best seed {display_seed}"
                )
            else:
                self.status_value.setText(str(status))
            if status == "PASS":
                self.status_value.setStyleSheet("color: #81C784; font-weight: bold;")
            else:
                self.status_value.setStyleSheet("color: #E57373; font-weight: bold;")

            report_path = info.get("report_path")
            self._set_report_title(report_path)
            self.report_path_value.setText(report_path or "—")

            slack = info.get("worst_slack")
            fmax = info.get("fmax")
            lines = list(info.get("summary_lines") or [])
            clocks = info.get("fmax_by_clock") or {}
            if clocks and not any(str(line).startswith("Fmax[") for line in lines):
                for clk, val in clocks.items():
                    lines.append(f"Fmax[{clk}]={val} MHz")
            if report_path and os.path.exists(report_path) and (
                not lines or slack is None or fmax is None
            ):
                # Fallback / refresh parse from disk
                try:
                    from .nextpnr_commands import NextPnRCommands
                    metrics = NextPnRCommands.parse_report_metrics(report_path)
                    if not lines:
                        lines = metrics.get("summary_lines") or []
                    if slack is None:
                        slack = metrics.get("worst_slack")
                    if fmax is None:
                        fmax = metrics.get("fmax")
                    if not clocks:
                        clocks = metrics.get("fmax_by_clock") or {}
                except Exception:
                    pass

            self.slack_value.setText(
                f"{slack} ns" if slack is not None else ("n/a (not in report)" if report_path else "—")
            )
            self.fmax_value.setText(
                f"{fmax} MHz" if fmax is not None else ("n/a (not in report)" if report_path else "—")
            )

            best_seed = info.get("best_seed")
            if best_seed is not None:
                self.best_value.setText(
                    f"seed {best_seed}  "
                    f"(slack={info.get('best_worst_slack')}, fmax={info.get('best_fmax')})"
                )
            else:
                self.best_value.setText("—")

            self.report_summary.setPlainText(
                "\n".join(lines) if lines else "(no timing/utilization fields in report)"
            )

            self._load_svg_pair(info.get("placed_svg"), info.get("routed_svg"))
            self._rebuild_results_table(info.get("results") or [])
            return

        if event == "multi_seed_done":
            self._finished = True
            self._stop_elapsed_timer()
            self.progress.setValue(self.progress.maximum())
            self._refresh_progress_format()
            if info.get("success"):
                self.status_value.setText(f"COMPLETE — best seed {info.get('best_seed')}")
                self.status_value.setStyleSheet("color: #81C784; font-weight: bold;")
                best_report = info.get("report_path")
                if not best_report:
                    for r in info.get("results") or []:
                        if r.get("is_best") and r.get("report_path"):
                            best_report = r.get("report_path")
                            break
                if best_report:
                    self._set_report_title(best_report)
                    self.report_path_value.setText(best_report)
                self._load_svg_pair(info.get("placed_svg"), info.get("routed_svg"))
            else:
                self.status_value.setText("FAILED")
                self.status_value.setStyleSheet("color: #E57373; font-weight: bold;")
            self._rebuild_results_table(info.get("results") or [])
            self.close_btn.setEnabled(True)
            return

    def _set_report_title(self, report_path: Optional[str]) -> None:
        """Show the active report basename in the timing group title."""
        if report_path and str(report_path).lower().endswith(".json"):
            self.timing_group.setTitle(
                f"Current seed timing — {os.path.basename(report_path)}"
            )
        elif report_path:
            # Don't retitle from non-json paths (e.g. SVG on done fallback)
            return
        else:
            self.timing_group.setTitle("Current seed timing (from report JSON)")

    def _load_one_svg(self, path: Optional[str], widget, fallback, path_label: QLabel, kind: str) -> None:
        if path and os.path.exists(path):
            path_label.setText(path)
            if widget is not None:
                try:
                    widget.load(path)
                except Exception as e:
                    path_label.setText(f"{path}\n(Could not render: {e})")
            elif fallback is not None:
                fallback.setText(f"{kind} SVG:\n{path}")
        else:
            path_label.setText(f"No {kind} SVG yet")

    def _load_svg_pair(self, placed: Optional[str], routed: Optional[str]) -> None:
        self._load_one_svg(
            placed, self.placed_svg_widget, self.placed_fallback, self.placed_path_label, "placed"
        )
        self._load_one_svg(
            routed, self.routed_svg_widget, self.routed_fallback, self.routed_path_label, "routed"
        )

    def _rebuild_results_table(self, results: List[Dict[str, Any]]) -> None:
        rows = sorted(results, key=lambda r: r.get("seed", 0))
        best_seed = None
        for r in rows:
            if r.get("is_best"):
                best_seed = r.get("seed")
                break
        self.results_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            seed = r.get("seed")
            status = "PASS" if r.get("success") else "FAIL"
            slack = r.get("worst_slack")
            fmax = r.get("fmax")
            is_best = bool(r.get("is_best")) or (best_seed is not None and seed == best_seed)
            values = [
                str(seed),
                "n/a" if slack is None else str(slack),
                "n/a" if fmax is None else str(fmax),
                status,
                "BEST" if is_best else "",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if status == "FAIL" and col == 3:
                    item.setForeground(Qt.red)
                elif status == "PASS" and col == 3:
                    item.setForeground(Qt.darkGreen)
                if is_best:
                    item.setForeground(Qt.blue)
                self.results_table.setItem(i, col, item)

    def closeEvent(self, event):
        # Allow closing once finished; while running, hide instead of aborting P&R
        if not self._finished:
            event.ignore()
            self.hide()
            return
        self._elapsed_timer.stop()
        super().closeEvent(event)
