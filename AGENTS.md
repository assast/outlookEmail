# AGENTS.md — Coding Agent Guidelines for outlookEmail

## Project Overview

Monolithic Flask web application for managing Outlook email accounts via Microsoft Graph API / IMAP.
Backend is a single Python file (`web_outlook_app.py`, ~4000 lines). Frontend is a vanilla JS SPA
in `templates/index.html` (~5800 lines, inline CSS/JS, macOS-style UI with Lucide icons).
SQLite database, no ORM. No frontend build pipeline.
Supports both Docker deployment (Linux) and Windows desktop exe (via PyInstaller + pywebview).

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
docker run -p 5000:5000 -e SECRET_KEY=your-secret -v $(pwd)/data:/app/data outlookemail
```
Production uses: `gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 --access-logfile - --preload web_outlook_app:app`

### Build Windows Desktop EXE
```bash
# On Windows only (PyInstaller cannot cross-compile)
pip install -r requirements.txt
pip install waitress pywebview pyinstaller
pyinstaller outlook_email.spec
# Output: dist/OutlookEmail.exe
```
Or push a `v*` tag to trigger GitHub Actions auto-build:
```bash
git tag v1.0.0
git push origin v1.0.0
# EXE published to GitHub Releases automatically
```

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
  run_windows.py              # Windows desktop entry point (pywebview + waitress)
  outlook_email.spec          # PyInstaller config (--onefile mode)
  outlook_mail_reader.py      # Standalone CLI email reader tool (independent)
  templates/
    index.html                # Main SPA (~5800 lines, inline JS/CSS, macOS-style UI)
    login.html                # Login page
  requirements.txt            # Python dependencies (minimums only)
  Dockerfile                  # Production container (Python 3.11-slim + gunicorn)
  .env.example                # Environment variable reference
  .github/workflows/
    docker-build-push.yml     # CI: Docker build + push to GHCR on main/master
    build-windows-exe.yml     # CI: Build Windows exe on v* tag push
  docs/plans/                 # Design and implementation plan documents
  img/                        # README screenshots
```

## Windows EXE Packaging (PyInstaller)

### Path Resolution Architecture
`web_outlook_app.py` handles frozen-environment path detection at module level:

```python
if getattr(sys, 'frozen', False):
    _resource_dir = sys._MEIPASS                     # templates (temporary, cleaned on exit)
    _base_dir = os.path.dirname(sys.executable)      # data persistence (exe directory)
    app.template_folder = os.path.join(_resource_dir, 'templates')
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))

DATABASE = os.getenv("DATABASE_PATH", os.path.join(_base_dir, "data", "outlook_accounts.db"))
```

### Runtime file layout (--onefile mode)
```
OutlookEmail.exe
├── sys._MEIPASS (temp dir, auto-cleaned)
│   ├── templates/index.html    ← Flask loads templates from here
│   └── web_outlook_app.py      ← imported as module
│
└── exe directory (persistent, survives upgrades)
    └── data/
        ├── outlook_accounts.db  ← SQLite database
        └── .secret_key          ← auto-generated SECRET_KEY
```

### Entry point: `run_windows.py`
- Generates and persists `SECRET_KEY` to `data/.secret_key` before importing Flask app
- Starts waitress WSGI server on auto-detected free port (background thread)
- Opens pywebview native desktop window (EdgeChromium backend)
- Falls back to browser if pywebview/WebView2 unavailable
- Closing window exits the program

### Key rules for packaging changes
- **Templates go into `_MEIPASS`** via `--add-data "templates;templates"` — read-only, temporary
- **Database goes into exe-local `data/`** — persistent, never in `_MEIPASS`
- **`web_outlook_app.py` is both the main app AND a data file** — added via `--add-data` so it can be imported from `_MEIPASS`
- **Do NOT add `waitress` or `pywebview` to `requirements.txt`** — they are Windows-only, installed separately in CI
- **`--console` mode is kept** to show server logs in a terminal window behind the GUI

## Frontend Architecture

### UI Framework
- **macOS / Apple Mail aesthetic** — Lucide SVG icons (CDN: `unpkg.com/lucide@0.469.0`), CSS variables for theming
- **CSS variables** defined at `:root`: `--mac-blue` (#007AFF), `--mac-green` (#34C759), `--mac-orange` (#FF9500), `--mac-red` (#FF3B30)
- **Lucide icons require `refreshIcons()`** (debounced 16ms wrapper around `lucide.createIcons()`) after every `innerHTML` assignment containing `<i data-lucide="...">`
- **DOMPurify** for HTML sanitization before DOM insertion

### Key frontend patterns
- `escapeHtml()` — null-safe HTML escaping; only one definition (duplicate was removed)
- `closeAllModals()` — covers all 10+ modals; called on Escape key
- SSE (Server-Sent Events) for streaming refresh operations; tracked via `_currentEventSource`
- No `transition: all` — use specific properties to avoid jank
- `backdrop-filter: blur()` only on navbar (GPU performance)

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
| Private globals    | `_underscore_prefix` | `_cipher_suite`, `_base_dir`   |
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
- Use `btn.innerHTML` (not `btn.textContent`) when content includes Lucide icon tags
- Call `refreshIcons()` after any `innerHTML` assignment containing `<i data-lucide="...">`
- Never use `<i data-lucide="...">` inside native `confirm()` / `alert()` dialogs (they cannot render HTML)

### Security Rules (Critical)
1. **Encryption:** Use Fernet symmetric encryption for stored credentials; prefix with `enc:`
2. **Password hashing:** bcrypt with auto-migration from plaintext
3. **Input sanitization:** Use `sanitize_input()` — HTML-escape, length limit, strip control chars
4. **Rate limiting:** IP-based tracking with configurable thresholds
5. **CSRF:** Flask-WTF with graceful degradation if unavailable
6. **Credential scrubbing:** Regex removal of tokens/passwords from error output and logs
7. **SECRET_KEY is mandatory** — app raises `RuntimeError` on startup if missing
8. **XSS prevention:** Always `escapeHtml()` server error messages before `innerHTML` insertion

### Configuration
All config via environment variables with fallback defaults. Reference `.env.example`:
```python
DATABASE = os.getenv("DATABASE_PATH", os.path.join(_base_dir, "data", "outlook_accounts.db"))
GPTMAIL_BASE_URL = os.getenv("GPTMAIL_BASE_URL", "https://mail.chatgpt.org.uk")
```

## CI/CD

### Docker (Linux deployment)
Workflow: `.github/workflows/docker-build-push.yml`
- Triggers on push to `main`/`master` when `.py`, `requirements.txt`, `Dockerfile`, or `templates/**` change
- Builds multi-arch Docker image (`linux/amd64`, `linux/arm64`)
- Pushes to GitHub Container Registry (`ghcr.io`)
- No lint, test, or quality gate steps

### Windows EXE (Desktop deployment)
Workflow: `.github/workflows/build-windows-exe.yml`
- Triggers on push of `v*` tags, or manual `workflow_dispatch`
- Runs on `windows-latest` with Python 3.11
- Installs `waitress`, `pywebview`, `pyinstaller` (not in requirements.txt)
- Builds single `OutlookEmail.exe` via `--onefile` mode
- Publishes to GitHub Releases with download instructions

## Key Architectural Notes

- **Single-file backend** — do not split into modules without explicit instruction
- **Single Gunicorn worker** (`-w 1`) — avoids SQLite locking and in-memory state issues
- **API fallback chain** — Graph API -> IMAP (new server) -> IMAP (old server) with retry
- **Proxy-per-group** — each account group supports its own HTTP/SOCKS5 proxy
- **No test infrastructure** — `.gitignore` excludes `/test*` files
- **Dual deployment** — Docker (Linux/server) and PyInstaller exe (Windows/desktop)
- **PyInstaller path split** — `sys._MEIPASS` for read-only resources, `sys.executable` dir for persistent data
- **Form accessibility** — all `<label>` elements have `for` attributes; color picker divs have `role="button"` + `tabindex="0"` + `aria-label`
