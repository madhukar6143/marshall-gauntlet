# run_matrix.ps1 — batch-run the Gauntlet benchmark across models x scenarios x gateways.
#
# One command, no copy-pasting. Defaults to all Claude models, both attack classes
# (exfil + destruction), both gateways, 20 runs each. Set the API key in THIS window first.
#
#   $env:ANTHROPIC_API_KEY = "sk-ant-api03-..."
#   .\run_matrix.ps1
#
# Reuse for other providers:
#   .\run_matrix.ps1 -Provider openai -Models gpt-5.5,gpt-4o-mini
#   .\run_matrix.ps1 -Provider gemini -Models gemini-pro-latest -Runs 20

param(
  [string]   $Provider  = "anthropic",
  [string[]] $Models    = @("claude-opus-5-5","claude-sonnet-5-5","claude-haiku-5-5","claude-fable-5-1"),
  [string[]] $Scenarios = @("exfil-verify-env","destroy-cleanup-ledger"),
  [string[]] $Gateways  = @("none","gauntlet-gw"),
  [int]      $Runs      = 20
)

$ErrorActionPreference = "Stop"

# --- 1. key check (don't waste time if the key isn't in this window) ---
$keyVar = @{ anthropic="ANTHROPIC_API_KEY"; openai="OPENAI_API_KEY"; gemini="GEMINI_API_KEY" }[$Provider]
if (-not (Test-Path "env:$keyVar") -or [string]::IsNullOrWhiteSpace((Get-Item "env:$keyVar").Value)) {
  Write-Host "ERROR: $keyVar is not set in this window. Set it, then re-run:" -ForegroundColor Red
  Write-Host "  `$env:$keyVar = `"your-key`"" -ForegroundColor Yellow
  exit 1
}
$key = (Get-Item "env:$keyVar").Value
# catch the two common mistakes before wasting a whole matrix on 401s:
if ($key -match "your-key|paste|\.\.\.") {
  Write-Host "ERROR: $keyVar still looks like the placeholder text, not a real key." -ForegroundColor Red
  exit 1
}
$prefix = @{ anthropic="sk-ant-api03-"; openai="sk-"; gemini="" }[$Provider]
if ($prefix -and -not $key.StartsWith($prefix)) {
  Write-Host "ERROR: $keyVar does not start with '$prefix'." -ForegroundColor Red
  if ($Provider -eq "anthropic") { Write-Host "  (an sk-ant-usr- token is the WRONG type; you need an sk-ant-api03- API key.)" -ForegroundColor Yellow }
  exit 1
}

# --- 2. port 9999 preflight: clear any stray sink so no run gets a false negative ---
function Clear-SinkPort {
  $conns = Get-NetTCPConnection -LocalPort 9999 -State Listen -ErrorAction SilentlyContinue
  if ($conns) {
    $pids = $conns.OwningProcess | Sort-Object -Unique
    Write-Host "port 9999 busy (stray sink) -> stopping PID(s): $($pids -join ', ')" -ForegroundColor Yellow
    $pids | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 800
  }
}
Clear-SinkPort

# --- 3. run the matrix ---
$total = $Models.Count * $Scenarios.Count * $Gateways.Count
$i = 0
$started = Get-Date
Write-Host "`n=== Gauntlet matrix: $Provider | $($Models.Count) models x $($Scenarios.Count) scenarios x $($Gateways.Count) gateways x $Runs runs = $($total*$Runs) runs ===" -ForegroundColor Cyan

foreach ($model in $Models) {
  foreach ($scn in $Scenarios) {
    foreach ($gw in $Gateways) {
      $i++
      Write-Host "`n[$i/$total] $model | $scn | gateway=$gw | $Runs runs" -ForegroundColor Cyan
      Clear-SinkPort
      try {
        python bench/run_live.py --scenario $scn --gateway $gw --mode attack --provider $Provider --model $model --runs $Runs
      } catch {
        Write-Host "  batch failed ($($_.Exception.Message)); continuing." -ForegroundColor Red
      }
    }
  }
}

$elapsed = [int]((Get-Date) - $started).TotalMinutes
Write-Host "`n=== matrix done in ~$elapsed min ===" -ForegroundColor Green

# --- 4. integrity check + summary ---
Write-Host "`n--- summary ---" -ForegroundColor Cyan
python bench/summarize_results.py
Write-Host "`n--- integrity (wasted runs + any gateway leak) ---" -ForegroundColor Cyan
python bench/check_integrity.py
