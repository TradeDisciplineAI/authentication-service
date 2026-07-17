# scripts/setup.ps1
$ErrorActionPreference = "Stop"

# Step 1: Syncing dependencies
Write-Host "Syncing dependencies..."
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to synchronize dependencies."
    Exit 1
}

# Step 2: Install pre-commit hooks
Write-Host "Installing pre-commit hooks..."
$hookPath = Join-Path (Get-Location) ".git\hooks\pre-commit"
if (Test-Path $hookPath) {
    Write-Host "Pre-commit already installed."
} else {
    uv run pre-commit install
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install pre-commit hooks."
        Exit 1
    }
}

# Step 3: Run validation
Write-Host "Running validation..."
uv run pre-commit run --all-files
if ($LASTEXITCODE -ne 0) {
    Write-Error "Validation failed."
    Exit 1
}

Write-Host "Setup completed successfully."
