$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath.TrimEnd('\')
$source = Join-Path $repoRoot 'dist-nuitka-standalone\monitor_controller.dist'
if (-not (Test-Path -LiteralPath (Join-Path $source 'MonitorToolbox2025.exe'))) {
    throw 'Build the standalone executable before packaging.'
}
$output = Join-Path $repoRoot 'dist-installer'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$stage = [IO.Path]::GetFullPath((Join-Path $output ('.package-' + [guid]::NewGuid().ToString('N'))))
if (-not $stage.StartsWith($output + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Package staging path escaped the output directory.'
}
try {
    New-Item -ItemType Directory -Path $stage | Out-Null
    $portable = Join-Path $stage 'MonitorToolbox2025-portable'
    Copy-Item -LiteralPath $source -Destination $portable -Recurse
    foreach ($name in 'README.md', 'README.upstream.md') {
        Copy-Item -LiteralPath (Join-Path $repoRoot $name) -Destination $portable
    }
    Compress-Archive -LiteralPath $portable -DestinationPath (Join-Path $output 'MonitorToolbox2025-portable.zip') -Force
}
finally {
    if (Test-Path -LiteralPath $stage) {
        $resolved = (Resolve-Path -LiteralPath $stage).ProviderPath
        if (-not $resolved.StartsWith($output + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Refusing to remove an unexpected package staging directory.'
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
