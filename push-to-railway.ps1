# ============================================
# 提交代码到 GitHub 并部署到 Railway
# ============================================

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor DarkGray
Write-Host "🚀 提交代码到 GitHub（Railway 自动部署）" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor DarkGray
Write-Host ""

# 检查是否在 git 仓库中
if (-not (Test-Path ".git")) {
    Write-Host "❌ 当前目录不是 Git 仓库" -ForegroundColor Red
    Write-Host ""
    Write-Host "请先初始化 Git：" -ForegroundColor Yellow
    Write-Host "  git init" -ForegroundColor White
    Write-Host "  git remote add origin https://github.com/你的用户名/gto-server.git" -ForegroundColor White
    Write-Host ""
    exit 1
}

# 显示修改的文件
Write-Host "📝 检查修改的文件..." -ForegroundColor Cyan
git status --short

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor DarkGray

# 询问提交信息
$commitMessage = Read-Host "📝 输入提交信息（直接回车使用默认）"
if ([string]::IsNullOrWhiteSpace($commitMessage)) {
    $commitMessage = "更新许可证服务器 - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

Write-Host ""
Write-Host "📦 添加文件..." -ForegroundColor Cyan
git add .

Write-Host "💾 提交..." -ForegroundColor Cyan
git commit -m "$commitMessage"

Write-Host "🚀 推送到 GitHub..." -ForegroundColor Cyan
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════" -ForegroundColor DarkGray
    Write-Host "✅ 代码已推送到 GitHub！" -ForegroundColor Green
    Write-Host "═══════════════════════════════════════════════════" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "🔄 Railway 正在自动部署..." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "📊 查看部署状态：" -ForegroundColor Cyan
    Write-Host "   1. 访问 https://railway.app" -ForegroundColor White
    Write-Host "   2. 进入你的项目" -ForegroundColor White
    Write-Host "   3. 点击 'Deployments' 查看进度" -ForegroundColor White
    Write-Host ""
    Write-Host "⏰ 预计 1-2 分钟完成部署" -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "❌ 推送失败！" -ForegroundColor Red
    Write-Host ""
    Write-Host "可能的原因：" -ForegroundColor Yellow
    Write-Host "  1. 未配置 Git 认证" -ForegroundColor White
    Write-Host "  2. 远程仓库地址错误" -ForegroundColor White
    Write-Host "  3. 网络问题" -ForegroundColor White
    Write-Host ""
    Write-Host "请检查并重试" -ForegroundColor Yellow
    Write-Host ""
}

