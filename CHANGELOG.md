# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-07-21

### Added
- `dxcli explain` command to output plain-English narrative diagnostic summaries.
- `ActiveWritersPanel` in the TUI to display processes with active write throughput.
- Integration tests for `explain` command, prediction ranges/variance, and TUI app instantiation.
- **Plugin Opt-In**: Community plugins are now disabled by default. Use `--enable-plugins` to run them safely.
- **Centralized State**: Created `dxcli/state.py` for atomic writes and strict directory permissions (`0700` dirs, `0600` files).
- **Heal Engine Scoping**: `heal` now strictly verifies that target paths are within the explicitly scanned scope and rejects symlink escapes.
- **Webhook Validation**: Added strict HTTP/HTTPS URL validation and safe timeouts for outbound alerts.
- **Exception Safety**: All database connections and long-running paths (watch, serve) now use robust `try/finally` lifecycle management.
- **CLI Normalization**: Extracted path-to-partition logic into a unified provider utility.
- **Static Quality Gates**: Added `flake8`, `black`, and `bandit` to the dev dependencies and updated workflow documentation.

### Changed
- Converted `dxcli watch` to default to interactive TUI mode when run in a tty (disabled via `--no-tui` option).
- Bounded prediction engine forecasts to suppress estimates beyond 365 days, and flag high-variance growth.
- Improved write attribution process matching using `/proc/<pid>/io` delta sampling on Linux and `psutil.Process.io_counters` fallback.
- Formatted the entire codebase with `black` and added a `.flake8` config; removed unused imports.
- `dxcli daemon` arguments are now strictly structured (e.g. `--target`, `--webhook`) rather than accepting arbitrary command injection.
- `dxcli serve` explicitly warns when binding to `0.0.0.0`.

### Fixed
- Fixed directory tree traversal, log finder, and stale file performance bottlenecks for fast (< 0.2s) scans.
- Fixed process handle query overhead in `ProcessMapper`, reducing inspection time from >100s to sub-second.
- Stabilized linear regression disk prediction calculations across rapid consecutive diagnostic runs.
- Added missing `from typing import List` import in `plugins/postgres_wal_analyzer.py`.
- Replaced decorative emojis in CLI output, HTML reports, TUI dashboard, and heal engine with text-only equivalents.
- Fixed path-prefix matching bugs in `process_mapper.py` and `runtime.py`.
- Updated Python floor requirement to Python 3.9+.
- Fixed crash in `dxcli diagnose --classify` caused by reference to non-existent `CATEGORIES` attribute (BUG-1).
- Redirected logrotate prescriptions to write safely to the scan scope's `.dx-prescriptions/` directory instead of `/etc/logrotate.d/` directly (BUG-2).
- Threaded the target `scan_path` through the rule evaluation engine to prevent rules firing on arbitrary working directories (BUG-3).
- Switched collectors to use `os.lstat` rather than `os.stat` to prevent following symlinks outside the scanned path (BUG-4).
- Prevented automatic creation of `~/.dx` upon importing `dxcli.config` via a lazy load implementation (BUG-5).
- Prevented infinite recursion cycles in `ClassificationEngine` by resolving symlinks cleanly and tracking visited directories (BUG-6).
- Replaced insecure metrics authentication timing comparison with constant-time `hmac.compare_digest` (BUG-7).
- Hardened webhook notifications against SSRF/DNS-rebinding by pinning IP resolutions and explicitly preventing HTTP redirects (BUG-8).
- Fixed anomaly detection threshold so leak rules fire correctly even with smaller history sets (BUG-9).
- Scoped TCPServer `allow_reuse_address` modification to metrics server instances rather than global class mutation (BUG-10).
- Fully implemented `max_depth` restriction in the DirectoryTreeCollector (BUG-11).
- Updated documentation to accurately reflect DirectoryTreeCollector's thread-per-child parallelism model (BUG-12).
- Normalized Bearer token check in metrics authorization to be case-insensitive (BUG-13).
- Enabled proper tracking and rendering of manual command instructions in heal engine instead of silent omissions (BUG-14).
- Expanded logrotate checker to detect rotated files utilizing standard `dateext` naming conventions (BUG-15).
- Replaced direct PowerShell command string construction with environment variables in the desktop notifier to prevent injection risks (BUG-16).


## [0.2.0] - 2026-05-12

### Added
- **Production Hardening**: Enforced 0700/0600 file permissions and systemd sandboxing.
- **Named Targets**: YAML configuration for registering frequently monitored paths.
- **Active Writer Detection**: Real-time throughput sampling (Bytes/sec) for attribution.
- **Semantic Classification**: Group disk usage by content type via `--classify`.
- **Daemon Management**: `dxcli daemon` for background process control.
- **Fleet Dashboard**: `dxcli fleet` command for multi-server observability.
- **Cross-Platform Alerts**: Native desktop notifications for Windows, macOS, and Linux.
- **CI/CD Wedge**: Automated pipeline mode with `--ci` flag.
- **Service Generation**: `generate-service` command for hardened systemd deployment.
- **Legacy Support**: Expanded compatibility down to Python 3.8+.

### Changed
- Migrated configuration from JSON to YAML.
- Upgraded `CorrelationEngine` with historical delta analysis.

## [0.1.2] - 2026-04-12

### Added
- **Heal Engine**: Automated remediation for identified disk issues.
- **Audit Logging**: Every action taken by `dxcli heal` is logged to `~/.dx/audit.log`.
- **Undo System**: `dxcli undo` allows reverting the last healing operation.
- **Python Version Guard**: Human-readable error if running on Python < 3.10.
- **CI/CD Pipeline**: GitHub Actions for automated testing and validation.
- **Contribution Guide**: `CONTRIBUTING.md` for new developers.
- **Issue Templates**: Bug report template for better community support.
- **Semantic Versioning Policy**: Clearly defined rules for future releases.

### Fixed
- Fixed missing entry point protection.
- Hardened `Prescription` model with action metadata.

## [0.1.1] - 2026-04-09

### Added
- Initial public release of `dxcli`.
- `diagnose`, `predict`, `watch`, and `dash` commands.
- Cross-platform support for Windows and Linux.
