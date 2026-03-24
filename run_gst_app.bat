@echo off
echo ==========================================
echo      GST Reconciliation Tool - TEST MODE
echo ==========================================
echo.
echo 1. Checking Dependencies...
pip install -r requirements.txt
echo.
echo 2. Checking Template File...
if not exist "static\files\gst_reco_template.xlsx" (
    echo    - Template missing. Generating new template...
    python make_template.py
) else (
    echo    - Template found.
)
echo.
echo 3. Starting Local Web Server...
echo    - The browser should open automatically.
echo    - Press CTRL+C to stop the server.
echo.
python app.py
pause
