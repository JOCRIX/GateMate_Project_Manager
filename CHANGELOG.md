# Changelog

All notable changes to GateMate Project Manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.2] - 2026-08-12

### Added

- **Post-implementation simulation** — Icarus Verilog (`iverilog` / `vvp`) flow: Verilog testbench + post-P&R netlist (`nextpnr --write` → Yosys `*_pnr.v`) + optional SDF, with VCD output for GTKWave.
- **Icarus toolchain support** — `iverilog` and `vvp` registered in toolchain paths, status probes, and Auto-Setup discovery (OSS CAD Suite).
- **Verilog testbenches** — Project hierarchy `testbench/verilog/`; Add Verilog Testbench; Simulation Status groups VHDL vs Verilog TBs with sources / timing / outputs trees.
- **Post-impl sim netlist from P&R** — Place & Route option to emit nextpnr `--write` JSON and export `netlist/<design>_pnr.v` (top renamed to the design name).
- **Bundled `cpesim.v`** — Physical GateMate cell models under `resources/gatemate/` (and project `testbench/verilog/`) for elaborating post-P&R primitives.
- **Implementation / Synthesis status trees** — Expandable Design/File trees with grouped outputs (impl/bitstream/timing/netlist, synth netlists, etc.).
- **Analysis viewers on nextpnr artifacts** — Timing / utilization / placement use nextpnr reports; Power Analysis remains unavailable/greyed for this flow.

### Changed

- **Launch Waveform Viewer** — Opens the newest VCD across behavioral, post-synthesis, and post-implementation (or the Simulation Status selection).
- **Post-Implementation Simulation dialog** — Intro text documents current open-toolchain limitations (functional post-P&R check; SDF IOPATH largely not annotated without vendor timing models).
- Icarus plusargs use sim-directory-relative paths so Windows project folders containing `--` do not break `vvp` / `$dumpfile`.
- Version bump to **0.4.2**.

### Fixed

- Place & Route dialog always cleared **Generate post-impl sim netlist** (`generate_sim_netlist` overwritten to `False` in collected settings).
- Tool command resolution falls back to configured / Auto-Setup absolute paths when process PATH is stale after Auto-Setup.
- Implementation status tree expansion / branch visibility on dark theme.

## [0.4.1] - 2026-08-10

### Added

- **Auto-Setup Toolchain** — One-time machine setup under Configuration: downloads pinned OSS CAD Suite and standalone GHDL, runs suite environment setup, persists User PATH / `YOSYSHQ_ROOT`, and stores global tool defaults for all future projects. Optional VS Code + TerosHDL path wiring.
- **OSS CAD GTKWave integration** — Status checks and Launch Waveform Viewer use absolute `bin\gtkwave.exe` with suite environment (`environment.bat` / in-process env), preferring DIRECT over bare PATH on Windows.

### Fixed

- **GTKWave Individual Tool Status ERROR** — `SimulationManager` / `GHDLCommands` no longer crash on missing `project_structure` before any probe runs (fresh install / no project).
- **Output flood on fresh start** — With no project loaded, path-structure and config-save failures are quiet; project/synthesis/implementation/simulation status panels idle instead of logging ERROR/WARNING spam. Real toolchain issues still surface.

### Changed

- Version bump to **0.4.1**.

## [0.4.0] - 2026-08-10

### Added

- **OSS CAD Suite GateMate flow** — Synthesis and implementation use standalone GHDL → Yosys `synth_gatemate -luttree -nomx8 -json` → `nextpnr-himbaechel` → `gmpack` `.bit`.
- **`nextpnr_commands.py`** — Place & Route / bitstream manager for nextpnr-himbaechel + gmpack (replaces proprietary `p_r` for GUI implementation).
- **`place_and_route_dialog.py`** — Expanded Place & Route settings UI: presets (Development / Timing Closure / Deep Optimization / Custom), device modes, SDC/frequency, seed modes, reports, Advanced options, and live command preview.
- **Multi-seed Place & Route** — Iterate seeds with selection criteria (best slack / Fmax / wirelength); optional early stop when timing is met.
- **Parallel multi-seed jobs** — Run concurrent nextpnr workers (`Parallel jobs`); progress window shows the current best seed when jobs > 1. Detected CPU core count is shown next to the control; Timing Closure and Deep Optimization presets default parallel jobs to core count.
- **Multi-seed progress window** — Live progress bar, per-seed timing/utilization from `*_report_seed_XXX.json`, side-by-side `_placed.svg` / `_routed.svg` previews, and results table.
- **OSS CAD Suite run environment** — Tool probes and nextpnr/gmpack subprocesses prepend OSS CAD `bin` + `lib` on PATH so Windows DLL loads succeed.
- **Configuration tool versions** — Individual Tool Status shows short version strings for GHDL, Yosys, nextpnr-himbaechel, gmpack, etc.
- **GateMate synth flow Advanced Check** — Validates standalone GHDL + Yosys `synth_gatemate` (replaces obsolete GHDL-Yosys plugin check for OSS CAD Yosys).
- **Configurable tool paths** — Tool locations come from PATH, `YOSYSHQ_ROOT`, or user Configuration (no hardcoded install directories).
- **Duplicate entity support** — Synthesis tree lists entities as `Entity (filename.vhdl)` so identical entity names in different files are selectable independently.
- **ZI board Test Connection `VERSION`** — Queries the STM32 `VERSION` console command and shows the firmware reply in the board selection results pane.
- **Synthesis strategy command preview** — Shows the GHDL + Yosys commands that will run.

### Changed

- Toolchain status / path editor tracks `ghdl`, `yosys`, `nextpnr_himbaechel`, `gmpack` (and optional `openFPGALoader`) instead of legacy `p_r`.
- GateMate synthesis no longer requires the Yosys GHDL plugin.
- Place & Route eligibility accepts `*_synth.json` netlists from the OSS CAD flow.
- nextpnr log severity prefers tool `Info:` / `Warning:` / `ERROR:` prefixes (avoids false ERRORs on lines like `fout error 0.000%`).
- Board Selection dialog cleanup: single combined header line; removed redundant “Selected: …” label under the board dropdown.

### Removed

- **Add Custom Board** button from the Upload tab.
- Automatic generation of template `.ccf` constraint files on project create.

### Fixed

- **View X Logs** after project create / synth / P&R — log viewers resolve the active project path and fall back to `logs/` on disk; Yosys/PnR loggers rebind when the project changes.
- **Toolchain structure spam** — Silenced repeated “toolchain structure already exists… Skipping.” noise.
- **Synthesis strategy dialog crash** — Command preview no longer depends on missing hierarchy helpers / uninitialized signals.
- **nextpnr / gmpack “Not available”** on Configuration when OSS CAD DLLs were not on PATH.

## [0.3.4] - 2026-07-10

### Fixed

- **Synthesis tab missing auto-added entities** — Entity discovery now opens the active project directory before reading the hierarchy, so VHDL files added by folder sync appear under Available Entities without a manual refresh.
- **Simulation testbench list** — Same project-directory lookup fix applied when loading testbenches.
- **Project config resolution** — `find_project_config()` prefers `current_project_path` when set, so tabs stay in sync even if the app working directory is elsewhere.

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
