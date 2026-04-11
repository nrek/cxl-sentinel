# Contributing to CXL Sentinel

Thank you for your interest in contributing. This document covers the basics for getting started.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Create a feature branch from `main`
4. Make your changes
5. Run the test suite
6. Submit a pull request

## Development Setup

```bash
git clone https://github.com/<your-fork>/cxl-sentinel.git
cd cxl-sentinel
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running Tests

```bash
pytest tests/ -v
```

## Code Standards

- Python 3.10+ is the minimum supported version.
- Follow PEP 8 for formatting. Use a linter (`flake8` or `ruff`) before committing.
- Keep dependencies minimal. The agent intentionally avoids heavy frameworks.
- Write tests for new features. Place them in the `tests/` directory.

## Pull Request Guidelines

- Keep PRs focused on a single change.
- Include a clear description of what changed and why.
- Reference any related issues.
- Ensure all tests pass before requesting review.

## Commit Messages

- Use present tense: "Add feature" not "Added feature"
- Keep the first line under 72 characters
- Reference issue numbers where applicable: `Fix token validation (#12)`

## Reporting Bugs

Open a GitHub issue with:

- Steps to reproduce
- Expected vs. actual behavior
- Python version, OS, and component (agent or API)
- Relevant log output (redact any tokens or secrets)

## Security Issues

Do **not** open public issues for security vulnerabilities. See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.
