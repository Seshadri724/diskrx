# Contributing to dxcli

Thank you for your interest in contributing to `dxcli`! This project aims to be the definitive tool for SREs and DevOps engineers managing disk health.

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Seshadri724/dxcli.git
   cd dxcli
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Or `venv\Scripts\activate` on Windows
   ```

3. **Install dependencies**:
   ```bash
   pip install -e ".[test]"
   ```

## Running Tests

We use `pytest` for our test suite. To run tests:

```bash
pytest tests/
```

## Pull Request Process

1. Create a new branch for your feature or bugfix.
2. Ensure all tests pass.
3. Update the `CHANGELOG.md` following the [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format.
4. Submit a Pull Request.

## Versioning Policy

We follow [Semantic Versioning (SemVer)](https://semver.org/):
- **Major (X.0.0)**: Breaking changes to the CLI interface or major architectural shifts.
- **Minor (0.X.0)**: New features, commands, or significant enhancements that are backwards compatible.
- **Patch (0.0.X)**: Bug fixes, documentation updates, and minor internal improvements.

## Code of Conduct

Please be respectful and professional in all interactions within this project.
