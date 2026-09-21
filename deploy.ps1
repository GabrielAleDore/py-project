# ==============================================================================
# Script de Deploy Automatizado: Reconciliation App -> Firebase Hosting + Cloud Run
# ==============================================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "   Iniciando Configuracao e Deploy no Firebase" -ForegroundColor Cyan
Write-Host "========================================================`n" -ForegroundColor Cyan

# 1. Verificar CLIs necessarias
Write-Host "[1/6] Verificando ferramentas instaladas..." -ForegroundColor Yellow

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Host "ERRO: O Google Cloud SDK (gcloud) nao foi encontrado no PATH." -ForegroundColor Red
    Write-Host "Instale em: https://cloud.google.com/sdk/docs/install" -ForegroundColor Red
    exit 1
}

if (-not (Get-Command firebase -ErrorAction SilentlyContinue)) {
    Write-Host "ERRO: O Firebase CLI nao foi encontrado no PATH." -ForegroundColor Red
    Write-Host "Execute: npm install -g firebase-tools" -ForegroundColor Red
    exit 1
}

Write-Host "  -> gcloud e firebase detectados com sucesso!" -ForegroundColor Green

# 2. Verificar autenticacao gcloud
Write-Host "`n[2/6] Verificando autenticacao no Google Cloud..." -ForegroundColor Yellow
$activeAccount = (gcloud auth list --filter=status:ACTIVE --format="value(account)")

if (-not $activeAccount) {
    Write-Host "  Nenhuma conta ativa detectada no gcloud. Abrindo login..." -ForegroundColor Cyan
    gcloud auth login
    $activeAccount = (gcloud auth list --filter=status:ACTIVE --format="value(account)")
}
Write-Host "  -> Conectado como: $activeAccount" -ForegroundColor Green

# 3. Selecionar o Projeto Firebase
Write-Host "`n[3/6] Identificando projeto Firebase..." -ForegroundColor Yellow
$paramProject = $args[0]

if (-not $paramProject) {
    $defaultProject = "py-projeto-23f39"
    Write-Host "Projeto padrao configurado: $defaultProject" -ForegroundColor Cyan
    $inputProject = Read-Host "Pressione [Enter] para usar '$defaultProject' ou digite outro Project ID"
    if ([string]::IsNullOrWhiteSpace($inputProject)) {
        $selectedProject = $defaultProject
    } else {
        $selectedProject = $inputProject.Trim()
    }
} else {
    $selectedProject = $paramProject.Trim()
}

Write-Host "  -> Projeto selecionado: $selectedProject" -ForegroundColor Green
gcloud config set project $selectedProject

# Configurar .firebaserc automaticamente
$firebasercContent = @"
{
  "projects": {
    "default": "$selectedProject"
  }
}
"@
Set-Content -Path ".firebaserc" -Value $firebasercContent -Encoding UTF8

# 4. Habilitar APIs necessarias no Google Cloud
Write-Host "`n[4/6] Garantindo que as APIs do Cloud Run e Cloud Build estao ativas..." -ForegroundColor Yellow
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project $selectedProject

# 5. Build e Deploy do container no Cloud Run
Write-Host "`n[5/6] Fazendo build e deploy do container no Cloud Run (regiao: us-central1)..." -ForegroundColor Yellow
Write-Host "  (Isso pode levar de 2 a 3 minutos no primeiro deploy)`n" -ForegroundColor Gray

gcloud run deploy reconciliation-app `
  --source . `
  --region us-central1 `
  --allow-unauthenticated `
  --port 8080 `
  --project $selectedProject

# 6. Deploy no Firebase Hosting
Write-Host "`n[6/6] Conectando Firebase Hosting ao servico do Cloud Run..." -ForegroundColor Yellow
firebase deploy --only hosting --project $selectedProject

Write-Host "`n========================================================" -ForegroundColor Green
Write-Host "   DEPLOY CONCLUIDO COM SUCESSO!" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Write-Host "Acesse sua aplicacao em:" -ForegroundColor Cyan
Write-Host "  👉 https://$selectedProject.web.app" -ForegroundColor Yellow
Write-Host "  👉 https://$selectedProject.firebaseapp.com" -ForegroundColor Yellow
Write-Host "========================================================`n" -ForegroundColor Green
