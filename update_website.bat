@echo off
setlocal
echo ==========================================
echo      GST Tool - Website Updater
echo ==========================================
echo.
echo Installing/Activating Git...
set "PATH=%PATH%;C:\Program Files\Git\cmd"

git remote get-url origin >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo No GitHub link connected yet.
    set /p REPO_URL="Enter your GitHub Repository URL (e.g. https://github.com/YourUsername/YourRepo.git): "
    git remote add origin %REPO_URL%
)

echo.
echo 1. Staging all changes...
git add .

echo.
git commit -m "Update GST tool"

echo.
echo 2. Pushing to GitHub (this updates the live site)...
git push -u origin master
if %ERRORLEVEL% NEQ 0 (
    git push -u origin main
)

echo.
echo Done! Render will now automatically update your site.
pause
