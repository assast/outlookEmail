# Outlook Email startup script

# Generate the key file if it does not exist.
if (-not (Test-Path "secret_key.txt")) {
    Write-Host "First run: generating SECRET_KEY..." -ForegroundColor Yellow
    python -c "import secrets; print(secrets.token_hex(32))" | Out-File -FilePath "secret_key.txt" -Encoding ascii -NoNewline
    Write-Host "SECRET_KEY saved to secret_key.txt" -ForegroundColor Green
    Write-Host ""
}

# Read and set SECRET_KEY.
$env:SECRET_KEY = Get-Content "secret_key.txt" -Raw

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Outlook Email Web App" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "URL: http://127.0.0.1:5000" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Start the app.
python web_outlook_app.py
