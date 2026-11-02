@echo off
setlocal
REM Wrapper untuk Windows Task Scheduler. Jadwalkan 18:00 WIB, Senin-Jumat.
REM
REM Path Python ditulis absolut: Task Scheduler tidak selalu mewarisi PATH
REM milik sesi interaktif, dan 'python' yang tidak ditemukan gagal dengan
REM exit code 9009 yang tidak menjelaskan apa pun.
set "PY=C:\Users\tazus\AppData\Local\Programs\Python\Python312\python.exe"
set "PROJ=C:\xampp\htdocs\Scrapping"

if not exist "%PY%" (
    echo FATAL: Python tidak ditemukan di %PY%
    exit /b 2
)

cd /d "%PROJ%" || exit /b 2
if not exist "%PROJ%\logs" mkdir "%PROJ%\logs"

REM Tabel keputusan ditulis ke stdout, bukan lewat logger. Tanpa pengalihan
REM ini, run terjadwal tidak meninggalkan jejak keputusan per emiten sama
REM sekali - hanya satu baris ringkasan di scanner.log.
"%PY%" -m ihsg_screener.cli %* >> "%PROJ%\logs\scheduler.log" 2>&1
set KODE=%ERRORLEVEL%
echo [%date% %time%] selesai dengan exit code %KODE% >> "%PROJ%\logs\scheduler.log"
exit /b %KODE%
