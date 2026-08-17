$ErrorActionPreference = 'Stop'

$repo = 'JeanMarc31110/fewura-crm'
$api = "https://api.github.com/repos/$repo/releases/latest"
$downloadDir = Join-Path $env:TEMP 'FEWURA-CRM-Installer'
$zipPath = Join-Path $downloadDir 'fewura-crm-latest.zip'

if (-not (Test-Path $downloadDir)) {
    New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null
}

Write-Host 'Récupération de la dernière release FEWURA CRM...'
try {
    $release = Invoke-RestMethod -Uri $api -Headers @{ 'User-Agent' = 'PowerShell' }
} catch {
    throw "Impossible de récupérer la dernière release publique GitHub pour $repo.`nVérifiez que le dépôt est public et qu'une release est publiée."
}

$asset = $release.assets | Where-Object { $_.name -match 'FEWURA_CRM_Setup\.exe$' -or $_.name -match 'fewura-crm-windows.*\.zip$' } | Sort-Object name -Descending | Select-Object -First 1
if (-not $asset) {
    throw "Aucune version Windows de l’installateur n’a été trouvée dans la dernière release GitHub."
}

Write-Host "Téléchargement : $($asset.name)"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath

if ($asset.name -match '\.exe$') {
    $installer = $zipPath
} else {
    $extractDir = Join-Path $env:LOCALAPPDATA 'FEWURA-CRM'
    if (-not (Test-Path $extractDir)) { New-Item -ItemType Directory -Path $extractDir -Force | Out-Null }
    Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
    $installer = Join-Path $extractDir 'agent.exe'
}

Write-Host 'Installation silencieuse du binaire FEWURA CRM...'
$proc = Start-Process -FilePath $installer -ArgumentList '/SILENT', '/NORESTART' -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    throw "L’installation silencieuse a échoué avec le code $($proc.ExitCode)."
}

Write-Host 'Installation terminée.'
