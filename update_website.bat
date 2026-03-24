@echo off
setlocal
echo ==========================================
echo      GST Tool - Website Updater
echo ==========================================
echo.
echo Installing/Activating Git...
set "PATH=%PATH%;C:\Program Files\Git\cmd"

if not exist ".git" (
    echo Initializing Git repository...
    git init
    echo.
    set /p REPO_URL="Enter your GitHub Repository URL (e.g. https://github.com/username/repo.git): "
    git remote add origin %REPO_URL%
)

echo.
echo 1. Staging all changes...
git add .

echo.
set /p COMMIT_MSG="Enter a description of your changes: "
git commit -m "%COMMIT_MSG%"

echo.
echo 2. Pushing to GitHub (this updates the live site)...
git push -f -u origin master

echo.
echo Done! Render will now update your site.
pause
