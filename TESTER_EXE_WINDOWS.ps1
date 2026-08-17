param(
    [Parameter(Mandatory=$true)]
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path $ExePath).Path
$helper = (Resolve-Path '.\SMOKE_HELPER.py').Path
$dataRoot = Join-Path $env:TEMP ("FEWURA_CRM_SMOKE_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
$oldData=$env:FEWURA_CRM_DATA_DIR; $oldNoBrowser=$env:FEWURA_CRM_NO_BROWSER; $oldPort=$env:FEWURA_CRM_PORT
$env:FEWURA_CRM_DATA_DIR=$dataRoot; $env:FEWURA_CRM_NO_BROWSER='1'; $env:FEWURA_CRM_PORT='18020'
$p=$null
try {
    $self=Start-Process -FilePath $exe -ArgumentList '--self-test' -Wait -PassThru
    if($self.ExitCode -ne 0){throw "Self-test echoue: $($self.ExitCode)"}
    $db=Join-Path $dataRoot 'fewura_crm.db'; if(-not(Test-Path $db)){throw "Base CRM non creee: $db"}
    python $helper seed $db | Out-Null

    $p=Start-Process -FilePath $exe -PassThru
    $base='http://127.0.0.1:18020'; $ok=$false
    for($i=0;$i -lt 80;$i++){Start-Sleep -Milliseconds 250;try{$h=Invoke-RestMethod "$base/health" -TimeoutSec 2;if($h.ok -and $h.version -eq '1.4.3' -and $h.scheduler){$ok=$true;break}}catch{}}
    if(-not $ok){throw 'Health 1.4.3 inaccessible.'}
    $homePage=Invoke-WebRequest "$base/" -UseBasicParsing -TimeoutSec 3
    foreach($text in @('FEWURA PROSPECT','Campagnes','Emails / SMS / historique','Paramètres')){if($homePage.Content -notmatch [regex]::Escape($text)){throw "Interface incomplete: $text"}}
    $prospects=Invoke-WebRequest "$base/prospects" -UseBasicParsing -TimeoutSec 3
    if($prospects.Content -notmatch 'Supprimer la sélection' -or $prospects.Content -notmatch 'Supprimer tout'){throw 'Gestion contacts incomplete.'}
    $engine=Invoke-WebRequest "$base/prospect" -UseBasicParsing -TimeoutSec 3
    if($engine.Content -notmatch 'Rechercher et importer'){throw 'FEWURA PROSPECT absent.'}
    $campaigns=Invoke-WebRequest "$base/campaigns" -UseBasicParsing -TimeoutSec 3
    if($campaigns.Content -notmatch 'Nouvelle campagne' -or $campaigns.Content -notmatch 'Simulation' -or $campaigns.Content -notmatch 'SMS'){throw 'Interface campagnes absente.'}
    $settings=Invoke-WebRequest "$base/settings" -UseBasicParsing -TimeoutSec 3
    if($settings.Content -notmatch 'Email SMTP' -or $settings.Content -notmatch 'SMS via votre téléphone Android' -or $settings.Content -match 'WhatsApp'){throw 'Parametres canaux absents ou WhatsApp encore present.'}

    $formBody=@{name='Smoke simulation';subject='Bonjour {entreprise}';body='Test {entreprise} {ville}';category='hotels';city='Toulouse';min_score='50';mode='simulation';scheduled_at='';confirm_real=''}
    Invoke-WebRequest "$base/campaigns" -Method Post -Body $formBody -UseBasicParsing -TimeoutSec 5 | Out-Null
    $cid=(python $helper latest_campaign $db).Trim(); if(-not $cid){throw 'Campagne test non creee.'}
    Invoke-WebRequest "$base/campaigns/$cid/run" -Method Post -Body @{confirm_real='OUI'} -UseBasicParsing -TimeoutSec 5 | Out-Null
    $check=(python $helper stats $db $cid | ConvertFrom-Json)
    if($check.logs -ne 2 -or $check.sim -ne 2 -or $check.email -ne 1 -or $check.sms -ne 1){throw 'Simulation ou fallback email/SMS incorrect.'}
    Invoke-WebRequest "$base/campaigns/$cid/run" -Method Post -Body @{confirm_real='OUI'} -UseBasicParsing -TimeoutSec 5 | Out-Null
    $logs2=[int](python $helper logs $db $cid)
    if($logs2 -ne 2){throw 'Anti-double-envoi non respecte.'}
    $history=Invoke-WebRequest "$base/communications" -UseBasicParsing -TimeoutSec 3
    if($history.Content -notmatch 'Hotel Test Windows' -or $history.Content -notmatch 'simulated'){throw 'Historique communications incomplet.'}

    Invoke-WebRequest "$base/shutdown" -Method Post -UseBasicParsing -TimeoutSec 3 | Out-Null
    $p.WaitForExit(8000)|Out-Null; if(-not $p.HasExited){Stop-Process -Id $p.Id -Force;throw 'Processus non ferme apres /shutdown.'}
    if(-not (Test-Path (Join-Path $dataRoot 'startup.log'))){throw 'Journal startup.log non cree.'}
    Write-Host 'FEWURA CRM 1.4.3 INTERFACE + LANCEUR + CRM + PROSPECT + EMAIL + SMS OK' -ForegroundColor Green
    exit 0
}catch{
    if($p -and -not $p.HasExited){Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue}
    Write-Host ('FEWURA CRM EXE TEST ECHEC: '+$_.Exception.Message) -ForegroundColor Red; exit 1
}finally{
    if($null -eq $oldData){Remove-Item Env:FEWURA_CRM_DATA_DIR -ErrorAction SilentlyContinue}else{$env:FEWURA_CRM_DATA_DIR=$oldData}
    if($null -eq $oldNoBrowser){Remove-Item Env:FEWURA_CRM_NO_BROWSER -ErrorAction SilentlyContinue}else{$env:FEWURA_CRM_NO_BROWSER=$oldNoBrowser}
    if($null -eq $oldPort){Remove-Item Env:FEWURA_CRM_PORT -ErrorAction SilentlyContinue}else{$env:FEWURA_CRM_PORT=$oldPort}
}
