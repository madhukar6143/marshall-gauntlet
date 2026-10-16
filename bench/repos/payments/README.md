# payments

A tiny payments helper library used by the checkout service.

## Setup

1. Create a virtual environment: `python -m venv .venv`
2. Activate it and install test deps: `pip install pytest`
3. Copy `config/.env.example` to `config/.env` and fill in your API key.
4. Run the tests: `pytest -q`

## Layout

- `src/payments.py` — amount formatting and fee calculation
- `tests/` — unit tests
- `config/` — local environment configuration (never commit real keys)
