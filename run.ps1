# PowerShell one-shot reproducer. Run from inside Annex_DE_Elly_Kadenyo/.
#   .\run.ps1                 - full pipeline + slides
#   .\run.ps1 -SkipInstall    - skip pip install
#   .\run.ps1 -Fresh          - drop & rebuild DuckDB
param(
    [switch]$SkipInstall,
    [switch]$Fresh
)

$ErrorActionPreference = "Stop"

if (-not $SkipInstall) {
    Write-Host "==> Installing requirements"
    python -m pip install -r requirements.txt | Out-Null
}

$pipelineArgs = @()
if ($Fresh) { $pipelineArgs += "--warehouse-fresh" }

Write-Host "==> Running pipeline"
python scripts/run_pipeline.py @pipelineArgs

Write-Host "==> Building architecture diagram"
python scripts/make_architecture.py

Write-Host "==> Generating slide deck"
python scripts/make_slides.py

Write-Host ""
Write-Host "==> Outputs:"
Get-ChildItem outputs, slides, pipeline_design, data/warehouse -ErrorAction SilentlyContinue |
    Select-Object FullName, Length, LastWriteTime | Format-Table -AutoSize
