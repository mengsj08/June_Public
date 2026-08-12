$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $RootDir

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PyLauncher) {
  & py -3 apps/review-studio/server.py --doctor --serve --open @args
  exit $LASTEXITCODE
}

& python apps/review-studio/server.py --doctor --serve --open @args
exit $LASTEXITCODE
