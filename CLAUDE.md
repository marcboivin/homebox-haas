# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build/Lint/Test Commands
- Lint check: `pylint homebox`
- Type check: `mypy homebox`
- Test: `pytest tests/`
- Single test: `pytest tests/test_file.py::test_function -v`

## Code Style Guidelines
- **Imports**: Group in order: standard lib, third-party, local
- **Typing**: Use type hints for function parameters and return values
- **Logging**: Use `_LOGGER` defined per module
- **Error Handling**: Use specific exceptions, handle API errors with HomeboxAuthError/HomeboxApiError
- **Naming**: snake_case for functions/variables, PascalCase for classes
- **Async**: Use async/await for all HTTP calls and I/O operations
- **Constants**: Define in const.py, use UPPERCASE
- **Documentation**: Docstrings following PEP 257

## Architecture Notes
- HomeboxAuthClient handles API communication
- HomeboxDataUpdateCoordinator manages data fetching
- Integration uses Home Assistant config entries and webhooks