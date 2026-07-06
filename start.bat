@echo off
REM Generate SECRET_KEY if not exists
if not exist "secret_key.txt" (
    python -c "import secrets; print(secrets.token_hex(32))" > secret_key.txt
)

REM Read SECRET_KEY
set /p SECRET_KEY=<secret_key.txt

REM Start application
python web_outlook_app.py
