# Contributing

## Scope

This repository is a customer-facing, read-only SDK for Aleatoric Hypercore services. Do not introduce signing, custody, or order-placement behavior.

## Workflow

1. Align on public API changes before implementation.
2. Preserve backward compatibility unless a versioned breaking change is explicitly approved.
3. Update tests, `README.md`, and `CHANGELOG.md` in the same pull request.
4. Keep examples runnable from the repository root.

## Local Validation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
pytest
mypy -p hypercore_sdk
python -m build
python -m twine check dist/*
```

## Support

- Email: [github@aleatoric.systems](mailto:github@aleatoric.systems)
- Discord: request the current customer support invite from the Aleatoric Systems team
