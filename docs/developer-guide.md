# Koda2 Developer Guide

Guide for developers contributing to or extending Koda2.

## Project Structure

```
Koda2/
├── koda2/
│   ├── api/               # FastAPI routes
│   ├── dashboard/         # Web dashboard (HTML/JS/CSS)
│   │   ├── templates/     # HTML templates
│   │   ├── static/        # CSS, JS, images
│   │   └── websocket.py   # Socket.IO handlers
│   ├── modules/           # All functional modules
│   │   ├── memory/        # Vector DB + profiles
│   │   ├── calendar/      # Multi-provider calendar
│   │   ├── email/         # Email providers
│   │   ├── messaging/     # Telegram + WhatsApp
│   │   ├── llm/           # LLM router
│   │   ├── images/        # Image generation
│   │   ├── documents/     # DOCX, XLSX, PDF, PPTX
│   │   ├── scheduler/     # Cron jobs
│   │   ├── macos/         # AppleScript integration
│   │   ├── travel/        # Flights & hotels
│   │   ├── meetings/      # Transcription & minutes
│   │   ├── expenses/      # Receipt processing
│   │   ├── facilities/    # Room booking & catering
│   │   ├── git_manager/   # Auto-commit
│   │   ├── task_queue/    # Parallel processing
│   │   └── metrics/       # System monitoring
│   ├── security/          # Encryption, RBAC, audit
│   ├── config.py          # Pydantic Settings
│   ├── database.py        # SQLAlchemy setup
│   ├── main.py            # FastAPI app entry
│   └── orchestrator.py    # Central coordinator
├── tests/                 # Test suite
├── docs/                  # Documentation
├── config/                # Runtime config
├── data/                  # Database & files
└── logs/                  # Application logs
```

## Module Architecture

### Standard Module Pattern

Every module follows this structure:

```python
# koda2/modules/example/__init__.py
from koda2.modules.example.service import ExampleService
from koda2.modules.example.models import ExampleModel

__all__ = ["ExampleService", "ExampleModel"]
```

```python
# koda2/modules/example/models.py
from pydantic import BaseModel

class ExampleModel(BaseModel):
    id: str
    name: str
```

```python
# koda2/modules/example/service.py
from koda2.logging_config import get_logger
from koda2.modules.example.models import ExampleModel

logger = get_logger(__name__)

class ExampleService:
    def __init__(self) -> None:
        pass
    
    async def do_something(self) -> ExampleModel:
        logger.info("doing_something")
        return ExampleModel(id="1", name="test")
```

## Adding a New Module

1. **Create directory:** `mkdir koda2/modules/my_module`

2. **Create files:**
   ```bash
   touch koda2/modules/my_module/__init__.py
   touch koda2/modules/my_module/models.py
   touch koda2/modules/my_module/service.py
   ```

3. **Implement service:**
   ```python
   # service.py
   class MyModuleService:
       def __init__(self) -> None:
           self._settings = get_settings()
   ```

4. **Wire into orchestrator:**
   ```python
   # koda2/orchestrator.py
   from koda2.modules.my_module import MyModuleService
   
   class Orchestrator:
       def __init__(self):
           # ... existing services ...
           self.my_module = MyModuleService()
   ```

5. **Add API routes:**
   ```python
   # koda2/api/routes.py
   @router.get("/my-module/items")
   async def list_items():
       orch = get_orchestrator()
       return await orch.my_module.list_items()
   ```

6. **Create tests:**
   ```bash
   touch tests/test_my_module.py
   ```

7. **Update documentation:**
   - Add to `docs/user-guide.md`
   - Update `docs/developer-guide.md`
   - Update `docs/README.md`

## Setup Wizard

The setup wizard (`setup_wizard.py`) handles initial configuration.

### Adding a New Configuration Section

```python
# In setup_wizard.py, add to main()

# ── My New Feature ───────────────────────────────────────────
print_header("My New Feature")
if ask_bool("Configure My Feature?"):
    config["MY_FEATURE_API_KEY"] = ask("API Key", secret=True)
    config["MY_FEATURE_ENABLED"] = "true"
```

### Configuration Helper Functions

Create a helper function for complex setup:

```python
def setup_my_feature() -> dict[str, str]:
    """Setup guide for my feature."""
    print_header("My Feature Setup")
    print("  Instructions...")
    
    config = {}
    if ask_bool("Enable?"):
        config["MY_FEATURE_KEY"] = ask("Key", secret=True)
    return config
```

## Web Dashboard

### Adding a New Dashboard Section

1. **Update the HTML template:** `koda2/dashboard/templates/index.html`
2. **Add navigation item:**
   ```html
   <div class="nav-item" data-section="my-feature">
       <span class="nav-icon">🔧</span>
       My Feature
   </div>
   ```

3. **Add content section:**
   ```html
   <section class="section" id="section-my-feature">
       <!-- Content -->
   </section>
   ```

4. **Add WebSocket handlers:**
   ```python
   # koda2/dashboard/websocket.py
   async def broadcast_my_feature_update(self, data: dict):
       await self.broadcast("my_feature_update", data)
   ```

## Testing

### Running Tests

```bash
# All tests
pytest

# With coverage report
pytest --cov=koda2 --cov-report=html

# Specific module
pytest tests/test_calendar.py -v

# Specific test
pytest tests/test_security.py::TestEncryption::test_encrypt_decrypt_roundtrip -v
```

### Writing Tests

```python
# tests/test_my_module.py
import pytest
from koda2.modules.my_module import MyModuleService

@pytest.fixture
def service():
    return MyModuleService()

@pytest.mark.asyncio
async def test_service_functionality(service):
    result = await service.do_something()
    assert result is not None
```

## Code Style

### Formatting

```bash
# Format all code
ruff format .

# Check and fix issues
ruff check . --fix
```

### Type Hints

Use strict type hints throughout:

```python
from typing import Optional

async def process(
    user_id: str,
    message: str,
    channel: str = "api",
) -> dict[str, Any]:
    ...
```

### Docstrings

Use Google-style docstrings:

```python
def process_receipt(
    self,
    image_path: str,
    submitted_by: str,
) -> Expense:
    """Process a receipt image and extract data.
    
    Args:
        image_path: Path to the receipt image.
        submitted_by: Email of the person submitting.
        
    Returns:
        Extracted expense data.
        
    Raises:
        FileNotFoundError: If image doesn't exist.
    """
```

## Logging

Use structlog for structured logging:

```python
from koda2.logging_config import get_logger

logger = get_logger(__name__)

# Info logging
logger.info("operation_started", user_id=user_id, action="create")

# Error logging
logger.error("operation_failed", error=str(exc), context=data)

# Debug logging
logger.debug("processing_item", item_id=item.id)
```

## Error Handling

Use tenacity for retries:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_external_data():
    # This will retry 3 times with exponential backoff
    return await api_call()
```

## Git Workflow

### Auto-Commit System

The git manager handles automatic commits:

```python
from koda2.modules.git_manager import GitManagerService

git = GitManagerService(llm_router)
await git.commit(
    message="Optional custom message",
    context="What changed and why"
)
```

### Commit Message Format

Follow conventional commits:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation
- `refactor:` Code refactoring
- `test:` Tests

## Database

### Adding a New Model

```python
# koda2/database.py
from sqlalchemy import Column, String, DateTime

class MyModel(Base):
    __tablename__ = "my_models"
    
    id = Column(String(36), primary_key=True)
    name = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
```

### Migrations

Currently using SQLite with auto-create. For production, consider Alembic.

## Security

### Encryption

```python
from koda2.security.encryption import encrypt, decrypt

# Encrypt sensitive data
encrypted = encrypt("sensitive data")

# Decrypt
decrypted = decrypt(encrypted)
```

### Audit Logging

```python
from koda2.security.audit import log_action

await log_action(
    user_id="user123",
    action="data_access",
    module="my_module",
    details={"resource": "sensitive_file"},
)
```

## API Design

### RESTful Patterns

```python
# List resources
@router.get("/items")
async def list_items() -> list[Item]:
    ...

# Get single resource
@router.get("/items/{item_id}")
async def get_item(item_id: str) -> Item:
    ...

# Create resource
@router.post("/items")
async def create_item(request: CreateItemRequest) -> Item:
    ...

# Update resource
@router.put("/items/{item_id}")
async def update_item(item_id: str, request: UpdateItemRequest) -> Item:
    ...

# Delete resource
@router.delete("/items/{item_id}")
async def delete_item(item_id: str) -> dict[str, str]:
    ...
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make changes with tests
4. Run tests: `pytest`
5. Format code: `ruff format .`
6. Commit: `git commit -m "feat: add my feature"`
7. Push: `git push origin feature/my-feature`
8. Create Pull Request

## Resources

- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Pydantic Docs](https://docs.pydantic.dev/)
- [SQLAlchemy Docs](https://docs.sqlalchemy.org/)
- [pytest Docs](https://docs.pytest.org/)
