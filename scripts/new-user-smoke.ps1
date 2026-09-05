[CmdletBinding()]
param(
    [string]$DBase = 'http://127.0.0.1:3001',
    [string]$ABase = 'http://127.0.0.1:8000'
)

$ErrorActionPreference = 'Stop'

function Invoke-JsonRequest {
    param(
        [string]$Method,
        [string]$Uri,
        [object]$Body,
        [string]$Token,
        [int]$TimeoutSec = 170
    )
    $params = @{ Method = $Method; Uri = $Uri; TimeoutSec = $TimeoutSec }
    if ($null -ne $Body) {
        $params.ContentType = 'application/json; charset=utf-8'
        # Windows PowerShell 5.1 encodes string bodies as ANSI unless the JSON
        # is sent as UTF-8 bytes, which corrupts Chinese research interests.
        $params.Body = [Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 10))
    }
    if ($Token) { $params.Headers = @{ Authorization = "Bearer $Token" } }
    return Invoke-RestMethod @params
}

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Get-ChineseText([int[]]$CodePoints) {
    $builder = New-Object System.Text.StringBuilder
    foreach ($code in $CodePoints) { [void]$builder.Append([char]$code) }
    return $builder.ToString()
}

Write-Host '==> New-user first-use smoke' -ForegroundColor Cyan
$email = "smoke-$([Guid]::NewGuid().ToString('N').Substring(0, 10))@example.com"
$password = 'smoke-first-use-123'

# 1. First login auto-registers a brand-new account.
$login = Invoke-JsonRequest 'Post' "$DBase/api/auth/login" @{ email = $email; password = $password }
Assert-True ([bool]$login.token) 'New-user login did not return a token.'
Write-Host "[OK] New user registered and logged in (id=$($login.user.id))" -ForegroundColor Green

# 2. Fill a minimal research profile (the onboarding step a real user does).
$gradeText = Get-ChineseText @(0x7855, 0x58EB, 0x4E00, 0x5E74, 0x7EA7)
$majorText = Get-ChineseText @(0x8BA1, 0x7B97, 0x673A, 0x79D1, 0x5B66, 0x4E0E, 0x6280, 0x672F)
$interestA = Get-ChineseText @(0x591A, 0x6A21, 0x6001, 0x5927, 0x6A21, 0x578B)
$interestB = Get-ChineseText @(0x5F3A, 0x5316, 0x5B66, 0x4E60)
$bioText = Get-ChineseText @(0x5173, 0x6CE8, 0x591A, 0x6A21, 0x6001, 0x5927, 0x6A21, 0x578B, 0x4E0E, 0x667A, 0x80FD, 0x4F53, 0x5E94, 0x7528)
$profile = @{
    nickname = 'Smoke New User'
    grade = $gradeText
    major = $majorText
    interests = @($interestA, $interestB)
    skills = @('PyTorch')
    bio = $bioText
}
$updated = Invoke-JsonRequest 'Put' "$DBase/api/user/profile" $profile $login.token
Assert-True (@($updated.interests).Count -ge 2) 'Profile update did not persist research interests.'
Write-Host '[OK] Research profile saved' -ForegroundColor Green

# 3. Personalized recommendations must return at least one verified mentor.
$recommend = Invoke-JsonRequest 'Get' "$DBase/api/recommend" $null $login.token
Assert-True ($recommend.needsOnboarding -eq $false) 'Recommendations still report needsOnboarding after profile save.'
Assert-True (@($recommend.recommendations).Count -ge 1) 'New user got no mentor recommendations.'
Write-Host "[OK] Recommendations returned $(@($recommend.recommendations).Count) mentors" -ForegroundColor Green

# 4. Model-backed research profile must complete and pass review.
$sw = [Diagnostics.Stopwatch]::StartNew()
$profileResult = Invoke-JsonRequest 'Post' "$DBase/api/user/research-profile" $null $login.token
$sw.Stop()
Assert-True ($profileResult.profile.type -eq 'research_profile') 'Research profile artifact type is wrong.'
Assert-True ($profileResult.profile.review_status -eq 'PASS') 'Research profile did not pass review.'
Write-Host "[OK] Research profile PASS in $([math]::Round($sw.Elapsed.TotalSeconds, 1))s" -ForegroundColor Green

# 5. Merged PDF analysis through A must not fail on semantic infrastructure.
$pdfBody = @{
    skill_id = 'pdf_analyze'
    message = 'Combined analysis (2 PDFs): SmokeA.pdf, SmokeB.pdf'
    execute_immediately = $false
    context = @{
        user_id = $email
        document_id = 'combined:smoke-a+smoke-b'
        document_ids = @('smoke-a', 'smoke-b')
        document_names = @('SmokeA.pdf', 'SmokeB.pdf')
        source_page_count = 2
        pages = @(
            @{
                page = 1
                text = 'This paper studies inference acceleration and lightweight deployment of multimodal large models, and how agents call vision-language models for research tasks.'
            }
            @{
                page = 2
                text = 'We propose low-rank fine-tuning to run multimodal large models efficiently on edge devices, combining knowledge distillation with reinforcement learning feedback.'
            }
        )
    }
}
$created = Invoke-JsonRequest 'Post' "$ABase/api/runs" $pdfBody
Assert-True ([bool]$created.run_id) 'PDF smoke run was not created.'
$runId = $created.run_id
$deadline = (Get-Date).AddMinutes(6)
$terminal = @('succeeded', 'failed', 'cancelled', 'waiting_for_user')
$result = $created
do {
    Start-Sleep -Seconds 3
    try { $result = Invoke-JsonRequest 'Get' "$ABase/api/runs/$runId/harness-result" } catch { }
} while ($result -and ($terminal -notcontains $result.status) -and (Get-Date) -lt $deadline)
Assert-True ($result.status -eq 'succeeded') "PDF smoke run ended with status $($result.status)."
Assert-True ($result.review_status -eq 'PASS') "PDF smoke run did not pass review: $($result.artifact.error)"
Write-Host '[OK] Merged PDF analysis PASS' -ForegroundColor Green

# Cleanup the temporary account (cascade removes its data).
try { Invoke-JsonRequest 'Delete' "$DBase/api/user/account" $null $login.token | Out-Null } catch { }

Write-Host ''
Write-Host 'All new-user first-use checks passed.' -ForegroundColor Green
