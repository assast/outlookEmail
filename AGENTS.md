# AGENTS.md — Coding Agent Guidelines for outlookEmail

## Project Overview

Monolithic Flask web application for managing Outlook email accounts via Microsoft Graph API / IMAP.
Backend is a single Python file (`web_outlook_app.py`, ~2500 lines). Frontend is a vanilla JS SPA
in `templates/index.html` with inline CSS/JS. SQLite database, no ORM. No frontend build pipeline.

## Build / Run / Test Commands

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run Development Server
```bash
# Requires SECRET_KEY env var at minimum
SECRET_KEY=dev-secret python web_outlook_app.py
```

### Run Production Server (Docker)
```bash
docker build -t outlookemail .
docker run -p 5000:5000 -e SECRET_KEY=your-secret outlookemail
```
Production uses: `gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 --access-logfile - --preload web_outlook_app:app`

### Testing
**There are no automated tests.** The `.gitignore` excludes `/test*` files. No test framework
is installed. If adding tests, use `pytest`:
```bash
pip install pytest
pytest tests/               # run all tests
pytest tests/test_foo.py    # run a single test file
pytest tests/test_foo.py::test_bar  # run a single test function
```

### Linting / Formatting
No linter or formatter is configured. Recommended tools if needed:
```bash
pip install ruff
ruff check web_outlook_app.py
ruff format web_outlook_app.py
```

## Project Structure

```
outlookEmail/
  web_outlook_app.py          # Main Flask app — ALL backend logic (routes, DB, auth, APIs)
  outlook_mail_reader.py      # Standalone CLI email reader tool (independent)
  templates/
    index.html                # Main SPA (1650+ lines, inline JS/CSS)
    login.html                # Login page
  requirements.txt            # Python dependencies (minimums only)
  Dockerfile                  # Production container (Python 3.11-slim + gunicorn)
  .env.example                # Environment variable reference
  .github/workflows/          # CI: Docker build + push to GHCR on main/master
  img/                        # README screenshots
```

## Code Style Guidelines

### Language
- **Backend:** Python 3.11+
- **Frontend:** Vanilla JavaScript (ES6+), HTML5, CSS3
- **Comments and UI text:** Written in **Chinese (Simplified)**

### Python Imports
Standard library first, then third-party, then local. All at module top level.
Use conditional imports with graceful degradation when a dependency is optional:
```python
try:
    from flask_wtf.csrf import CSRFProtect, generate_csrf
    CSRF_AVAILABLE = True
except ImportError:
    CSRF_AVAILABLE = False
```

### Naming Conventions
| Element            | Convention         | Example                          |
|--------------------|--------------------|----------------------------------|
| Functions          | `snake_case`       | `get_access_token_graph()`       |
| Constants          | `UPPER_SNAKE_CASE` | `TOKEN_URL_GRAPH`, `MAX_LOGIN_ATTEMPTS` |
| Variables          | `snake_case`       | `login_attempts`, `export_verify_tokens` |
| Private globals    | `_underscore_prefix` | `_cipher_suite`                |
| Route paths        | kebab-case in URL  | `/api/accounts/refresh-all`      |

### Type Annotations
Use Python type hints on all function signatures:
```python
def check_rate_limit(ip: str) -> tuple[bool, Optional[int]]:
def load_accounts(group_id: int = None) -> List[Dict]:
def build_error_payload(
    code: str, message: str, err_type: str = "Error",
    status: int = 500, details: Any = None,
    trace_id: Optional[str] = None
) -> Dict[str, Any]:
```

### Error Handling
Use structured error payloads with trace IDs. Always sanitize sensitive data from errors:
```python
# Return result objects with success flag
def some_operation(...) -> Dict[str, Any]:
    try:
        ...
        return {"success": True, "data": result}
    except Exception as exc:
        return {"success": False, "error": build_error_payload(
            code="OPERATION_FAILED", message=str(exc),
            err_type="OperationError", status=500
        )}
```
- Use `build_error_payload()` for standardized error responses
- Never expose raw tokens, passwords, or secrets in error messages
- Generate UUID `trace_id` for each error for log correlation

### Database Pattern
Use Flask `g` context for SQLite connections. Always use `sqlite3.Row` factory.
Raw SQL only (no ORM). Schema migrations are inline `ALTER TABLE` with column existence checks:
```python
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db
```

### API Design
RESTful JSON endpoints under `/api/`:
- `GET /api/<resource>` — list
- `POST /api/<resource>` — create
- `PUT /api/<resource>/<id>` — update
- `DELETE /api/<resource>/<id>` — delete
- Use Server-Sent Events (SSE) for streaming long operations

### Frontend JavaScript
- Vanilla JS only — no frameworks, no modules, no bundler
- Use `async/await` with `fetch()` for API calls
- DOM access via `document.getElementById()`
- Sanitize all HTML with `DOMPurify.sanitize()` before DOM insertion
- All JS/CSS is inline within HTML templates

### Security Rules (Critical)
1. **Encryption:** Use Fernet symmetric encryption for stored credentials; prefix with `enc:`
2. **Password hashing:** bcrypt with auto-migration from plaintext
3. **Input sanitization:** Use `sanitize_input()` — HTML-escape, length limit, strip control chars
4. **Rate limiting:** IP-based tracking with configurable thresholds
5. **CSRF:** Flask-WTF with graceful degradation if unavailable
6. **Credential scrubbing:** Regex removal of tokens/passwords from error output and logs
7. **SECRET_KEY is mandatory** — app raises `RuntimeError` on startup if missing

### Configuration
All config via environment variables with fallback defaults. Reference `.env.example`:
```python
DATABASE = os.getenv("DATABASE_PATH", "data/outlook_accounts.db")
GPTMAIL_BASE_URL = os.getenv("GPTMAIL_BASE_URL", "https://mail.chatgpt.org.uk")
```

## CI/CD

Single GitHub Actions workflow (`.github/workflows/docker-build-push.yml`):
- Triggers on push to `main`/`master` when `.py`, `requirements.txt`, `Dockerfile`, or `templates/**` change
- Builds multi-arch Docker image (`linux/amd64`, `linux/arm64`)
- Pushes to GitHub Container Registry (`ghcr.io`)
- No lint, test, or quality gate steps

## Key Architectural Notes

- **Single-file backend** — do not split into modules without explicit instruction
- **Single Gunicorn worker** (`-w 1`) — avoids SQLite locking and in-memory state issues
- **API fallback chain** — Graph API -> IMAP (new server) -> IMAP (old server) with retry
- **Proxy-per-group** — each account group supports its own HTTP/SOCKS5 proxy
- **No test infrastructure** — `.gitignore` excludes `/test*` files
