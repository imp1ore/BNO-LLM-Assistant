@echo off
echo ========================================
echo BNO LLM Assistant - Push to GitHub
echo Beta v1.0.0
echo ========================================
echo.

REM Check if Git is installed
where git >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Git is not installed or not in PATH.
    echo Please install Git from: https://git-scm.com/download/win
    pause
    exit /b 1
)

cd /d "%~dp0"

echo [1/6] Setting up remote repository...
git remote remove origin 2>nul
git remote add origin https://github.com/imp1ore/BNOLLM.git
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Remote might already exist, continuing...
    git remote set-url origin https://github.com/imp1ore/BNOLLM.git
)
echo [OK] Remote configured

echo.
echo [2/6] Adding all files...
git add .
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to add files
    pause
    exit /b 1
)
echo [OK] Files staged

echo.
echo [3/6] Creating commit...
git commit -m "Beta v1.0.0 - Initial release: BNO LLM Assistant demo ready

Features:
- User authentication and admin panel
- Document upload (PDF, DOCX, PPTX, TXT) with drag & drop
- AI chat with RAG-based responses
- Chat history management
- e& branding and modern UI
- Local Ollama integration
- Vector database for document indexing"
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] No changes to commit (might already be committed)
)

echo.
echo [4/6] Creating version tag...
git tag -a v1.0.0-beta -m "Beta Release v1.0.0 - BNO LLM Assistant" 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Tag created: v1.0.0-beta
) else (
    echo [INFO] Tag might already exist
)

echo.
echo [5/6] Verifying setup...
git log --oneline -1
echo.
git tag -l
echo.

echo [6/6] Ready to push!
echo.
echo ========================================
echo Next: Push to GitHub
echo ========================================
echo.
echo Run these commands:
echo.
echo   git push -u origin main
echo   git push origin v1.0.0-beta
echo.
echo If "main" doesn't work, try:
echo   git push -u origin master
echo.
echo ========================================
echo.
echo IMPORTANT: Make sure you're authenticated!
echo GitHub may require a Personal Access Token.
echo Create one at: https://github.com/settings/tokens
echo.
pause

