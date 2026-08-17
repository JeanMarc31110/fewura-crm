$ErrorActionPreference = 'Stop'

$downloadUrl = 'https://github.com/JeanMarc31110/fewura-crm/releases/download/installer-e338bd6/fewura-crm-windows-e338bd6.zip'
$downloadDir = Join-Path $env:LOCALAPPDATA 'FEWURA-CRM'
$zipPath = Join-Path $env:TEMP 'fewura-crm-latest.zip'

Write-Host 'Téléchargement du binaire Windows FEWURA CRM...'
if (-not (Test-Path $downloadDir)) {
    New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null
}

Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath

$targetDir = Join-Path $downloadDir 'app'
if (Test-Path $targetDir) {
    Remove-Item $targetDir -Recurse -Force
}
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

Write-Host 'Extraction du binaire...'
Expand-Archive -Path $zipPath -DestinationPath $targetDir -Force

$exe = Join-Path $targetDir 'agent.exe'
if (-not (Test-Path $exe)) {
    throw "Le binaire agent.exe est introuvable après extraction dans $targetDir"
}

Write-Host "Installation terminée. Dossier : $targetDir"
Start-Process -FilePath $exe -WorkingDirectory $targetDir
