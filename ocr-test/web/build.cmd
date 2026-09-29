@echo off
rem Windows-версія build.sh: збирає папку dist\ зі сторінкою та файлами рушія Tesseract.js (усе локально, без CDN).
rem Потрібні Node.js (npm) і Windows 10 або новіша: tar і PowerShell там уже є.
setlocal
for /f "tokens=2 delims=:." %%c in ('chcp') do set "OLDCP=%%c"
chcp 65001 >nul
pushd "%~dp0"
set "BUILD_TMP=%TEMP%\ocr-build-%RANDOM%%RANDOM%"
mkdir "%BUILD_TMP%" || goto fail

pushd "%BUILD_TMP%"
call npm pack -s tesseract.js@7.0.0 tesseract.js-core@7.0.0 ^
  @tesseract.js-data/ukr@1.0.0 @tesseract.js-data/rus@1.0.0 @tesseract.js-data/eng@1.0.0 ^
  pdfjs-dist@3.11.174 utif@3.1.0 pako@1.0.11 >nul
if errorlevel 1 (popd & goto fail)
for %%f in (*.tgz) do (
  mkdir "%%~nf"
  tar xzf "%%f" -C "%%~nf" || (popd & goto fail)
)
popd

if exist dist rmdir /s /q dist
mkdir dist\core dist\lang dist\samples
set "PKG=%BUILD_TMP%\tesseract.js-7.0.0\package\dist"
set "CORE=%BUILD_TMP%\tesseract.js-core-7.0.0\package"
set "PDFJS=%BUILD_TMP%\pdfjs-dist-3.11.174\package\build"
copy /y ocr.html dist\ >nul || goto fail
copy /y ocr-worker.js dist\ >nul || goto fail
copy /y "%PKG%\tesseract.min.js" dist\ >nul || goto fail
copy /y "%PKG%\worker.min.js" dist\ >nul || goto fail
copy /y "%CORE%\tesseract-core-relaxedsimd-lstm.wasm.js" dist\core\ >nul || goto fail
copy /y "%CORE%\tesseract-core-simd-lstm.wasm.js" dist\core\ >nul || goto fail
copy /y "%CORE%\tesseract-core-lstm.wasm.js" dist\core\ >nul || goto fail
copy /y "%PDFJS%\pdf.min.js" dist\ >nul || goto fail
copy /y "%PDFJS%\pdf.worker.min.js" dist\ >nul || goto fail
copy /y "%BUILD_TMP%\utif-3.1.0\package\UTIF.js" dist\utif.js >nul || goto fail
copy /y "%BUILD_TMP%\pako-1.0.11\package\dist\pako_inflate.min.js" dist\ >nul || goto fail
copy /y ..\samples\scan_invoice.pdf dist\samples\ >nul || goto fail
for %%l in (ukr rus eng) do (
  call :b64 "%BUILD_TMP%\tesseract.js-data-%%l-1.0.0\package\4.0.0_best_int\%%l.traineddata.gz" "dist\lang\%%l.traineddata.gz.b64.txt" || goto fail
)
call :b64 ..\samples\scan_invoice_g4.tif dist\samples\scan_invoice_g4.tif.b64.txt || goto fail

echo Готово. Локально: py -m http.server -d dist, далі http://localhost:8000/ocr.html
set "RC=0"
goto done

:fail
echo Збірка не вдалася.
set "RC=1"

:done
if exist "%BUILD_TMP%" rmdir /s /q "%BUILD_TMP%"
popd
chcp %OLDCP% >nul
exit /b %RC%

rem Файл -> base64 одним рядком (як base64 -w0).
:b64
set "B64_IN=%~f1"
set "B64_OUT=%~f2"
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; [IO.File]::WriteAllText($env:B64_OUT, [Convert]::ToBase64String([IO.File]::ReadAllBytes($env:B64_IN)))"
exit /b %errorlevel%
