# CI checks: use only synthetic files in a new temporary directory, never a game DLL.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$repo = Split-Path -Parent $PSScriptRoot
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('sof-patch-check-' + [Guid]::NewGuid().ToString('N'))
$payload = Join-Path $fixture 'third_player_mod'
$script = Join-Path $payload 'patch.ps1'
$dll = Join-Path $fixture 'GameAssembly.dll'
New-Item -ItemType Directory -Path $payload -Force | Out-Null

function Invoke-Refusal([string]$Action, [string]$Expected) {
    $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Action $Action -GameFolder $fixture 2>&1
    if ($LASTEXITCODE -ne 1 -or ($output | Out-String) -notlike "*$Expected*") {
        throw "Expected refusal for $Action; exit=$LASTEXITCODE; output=$output"
    }
    if (@(Get-ChildItem -LiteralPath $fixture -File).Count -gt 1) {
        throw 'Refused operation created a backup or staged file.'
    }
}

try {
    # Parse all PowerShell sources without executing the game-dependent test.
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $repo 'third_player_mod') -Filter '*.ps1') {
        $tokens = $null
        $errors = $null
        [void][Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
        if ($errors.Count -gt 0) { throw "PowerShell syntax error in $($file.Name): $errors" }
    }
    Copy-Item -LiteralPath (Join-Path $repo 'third_player_mod/patch.ps1') -Destination $script
    Copy-Item -LiteralPath (Join-Path $repo 'third_player_mod/release-plan.json') -Destination $payload
    $bytes = [Text.Encoding]::ASCII.GetBytes('Synthetic unsupported input. This is not a game DLL.')
    [IO.File]::WriteAllBytes($dll, $bytes)
    $before = (Get-FileHash -Algorithm SHA256 -LiteralPath $dll).Hash
    foreach ($action in @('Check', 'Install', 'Uninstall')) {
        Invoke-Refusal $action 'This game version is not supported'
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $dll).Hash -ne $before) {
            throw 'A refused action modified its input.'
        }
    }
    [IO.File]::AppendAllText((Join-Path $payload 'release-plan.json'), ' ')
    Invoke-Refusal 'Install' 'The download is incomplete or damaged'
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $dll).Hash -ne $before) {
        throw 'Modified patch data changed its input.'
    }
    Copy-Item -LiteralPath (Join-Path $repo 'third_player_mod/release-plan.json') -Destination $payload -Force
    [IO.File]::Delete($dll)
    Invoke-Refusal 'Install' 'Game not found'
    Write-Host 'PASS: PowerShell parsing, three unknown-DLL refusals, corrupt-plan refusal and missing-DLL refusal.'
} finally {
    [IO.Directory]::Delete($fixture, $true)
}
exit 0
