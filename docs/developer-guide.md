# Koda2 Developer Guide

## Project Structure

```
Koda2/
├── koda2/           # Main package
│   ├── api/               # FastAPI route definitions
│   ├── modules/           # Functional modules (1-10)
│   │   ├── memory/        # Vector DB + structured user profiles
│   │   ├── calendar/      # Multi-provider calendar management
│   │   ├── email/         # IMAP/SMTP and Gmail integration
│   │   ├── messaging/     # Telegram + WhatsApp bots
│   │   ├── llm/           # LLM provider abstraction + router
│   │   ├── images/        # Image generation + vision analysis
│   │   ├── documents/     # Document generation + templates
│   │   ├── scheduler/     # APScheduler-based task system
│   │   ├── macos/         # AppleScript + shell integration
│   │   └── self_improve/  # Plugin system + auto-code generation
│   ├── security/          # Encryption, RBAC, audit logging
│   ├── config.py          # Pydantic Settings (env-based)
│   ├── database.py        # Async SQLAlchemy engine/session
│   ├── logging_config.py  # Structlog configuration
│   ├── orchestrator.py    # Central request processing brain
│   └── main.py            # FastAPI app + lifespan
├── tests/                 # Test suite
├── plugins/               # Dynamic plugin directory
├── templates/             # Jinja2 templates
├── docs/                  # Documentation
├── config/                # Runtime config files
├── data/                  # Runtime data (DB, ChromaDB, generated files)
└── logs/                  # Application logs
```

## Module Architecture

Each module follows a consistent pattern:

```
module/
├── __init__.py    # Public exports
├── models.py      # Pydantic models and SQLAlchemy entities
├── providers.py   # External service implementations (optional)
└── service.py     # Business logic orchestrating providers
```

## Adding a New Module

1. Create directory under `koda2/modules/`
2. Implement `__init__.py` with public exports
3. Create `service.py` with the main service class
4. Wire into `orchestrator.py`
5. Add API routes in `koda2/api/routes.py`
6. Create tests in `tests/test_<module>.py`
7. Update documentation

## Creating Plugins

Plugins extend Koda2 dynamically. Place `.py` files in the `plugins/` directory.

```python
class MyPlugin:
    name = "my_plugin"
    description = "Does something useful"
    version = "0.1.0"
    capabilities = ["my_capability"]

    async def execute(self, **kwargs):
        return "result"

def register():
    return MyPlugin()
```

Plugins are auto-loaded at startup and can also be generated via the self-improvement engine.

## Testing

```bash
# All tests with coverage
pytest

# Specific module
pytest tests/test_calendar.py -v

# Single test
pytest tests/test_security.py::TestEncryption::test_encrypt_decrypt_roundtrip -v
```

## Code Style

- **Formatter/Linter:** Ruff (configured in `pyproject.toml`)
- **Type Checking:** mypy strict mode
- **Docstrings:** Google style
- **Async:** All I/O operations must be async
- **Error Handling:** Use tenacity for retries, structlog for logging
