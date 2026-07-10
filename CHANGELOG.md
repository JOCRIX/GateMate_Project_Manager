# Changelog

All notable changes to GateMate Project Manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.3] - 2026-07-10

### Added

- **Automatic project folder sync** — While a project is loaded, the manager scans `src/`, `testbench/`, and `constraints/` every 5 seconds for changes made outside the GUI.
- **Auto-add detected files** — New VHDL and constraint files dropped into project folders are registered automatically and the relevant tabs refresh.
- **Auto-remove deleted files** — VHDL entries missing from disk are removed from the project hierarchy; deleted constraint files are detected and the Implementation tab refreshes.

### Changed

- **Detect Manual Files** now performs a full two-way sync (add new files, remove deleted ones) instead of add-only detection.
- Default auto-scan interval reduced from 30s to 5s (configurable via `~/.cc_project_manager/settings.json`).

## [0.3.2] - 2026-07-10

### Added

- **Zector Instruments ZI-0001 board support** — ZI-0001-0001 Logic 1.0 GateMate A1 is now a built-in board (`zi_0001_0001_logic1`), listed first in the board dropdown and used as the default board.
- **ZI FPGA Loader integration** — Bundled serial loader (`zi_fpga_loader.py`) and manager (`zi_fpga_loader_manager.py`) for programming GateMate FPGAs over the on-board STM32 loader via COM port.
- **Upload manager factory** — `upload_manager_factory.py` selects the correct programming backend (`ZiFPGALoaderManager` or `OpenFPGALoaderManager`) based on board configuration.
- **COM port configuration** — FPGA Board Selection dialog includes a COM port field and serial port test for Zector boards.
- **Live programming progress in Output** — Serial loader progress (TX/RX, bytes sent, percentage, STM32 result) is streamed to the GUI Output window during SRAM programming.
- **Upload progress bar updates** — Progress bar and status label update from loader percentage messages (thread-safe via Qt signals).
- **`pyserial` dependency** — Required for ZI FPGA Loader serial communication.

### Changed

- Window title bar, About dialog, and application name now read the version from `cc_project_manager_pkg.__version__` instead of a hardcoded value.
- CLI header banner uses the package version dynamically.

### Fixed

- **Crash during Program SRAM** — Upload progress UI updates are now dispatched on the main thread, preventing PyQt crashes when programming from a worker thread.
- **P&R constraint validation** — Empty or all-commented `.ccf` constraint files are detected before Place & Route with a clear error message.
- **P&R error reporting** — Improved extraction of concise P&R failure summaries; reduced duplicate/generic error flooding in the Output window.
- **Implementation log visibility** — Errors shown in the Output window are also written to the implementation log.
- **Constraint file resolution** — Design-specific constraint files are preferred when resolving which `.ccf` to use for Place & Route.

## [0.3.1] - 2026-07-10

### Changed

- Version bump and release housekeeping.

## [0.3.0] - 2026-07-10

### Added

- Constraint file validation and improved Place & Route error handling groundwork.

### Changed

- Version numbering updated to 0.3.x series.

## [0.2.0] - Earlier

### Added

- Initial public release with GUI and CLI interfaces.
- Project management, synthesis (Yosys), simulation (GHDL/GTKWave), implementation (Place & Route), and upload (openFPGALoader) workflows.
- Olimex and Cologne Chip GateMate EVB board support.
- Dark-mode PyQt5 GUI.
