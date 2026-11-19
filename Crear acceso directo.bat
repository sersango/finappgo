@echo off
rem ==========================================================================
rem  Crear acceso directo.bat  -  Pone el icono de FinAppGo en tu Escritorio
rem
rem  Texto plano: puedes abrirlo con el Bloc de notas. Solo crea un acceso
rem  directo llamado "FinAppGo" que abre Iniciar.bat, con el icono de la app.
rem  No instala nada ni toca nada mas. Si mueves la carpeta de FinAppGo, vuelve
rem  a hacer doble clic aqui para crear el acceso directo de nuevo.
rem ==========================================================================
setlocal
cd /d "%~dp0"
if not exist "%~dp0Iniciar.bat" (
  echo  No encuentro Iniciar.bat en esta carpeta.
  if not defined FINAPPGO_ESCRITORIO pause
  exit /b 1
)
set "FINAPPGO_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = $env:FINAPPGO_ESCRITORIO; if (-not $d) { $d = [Environment]::GetFolderPath('Desktop') }; $s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'FinAppGo.lnk')); $s.TargetPath = Join-Path $env:FINAPPGO_DIR 'Iniciar.bat'; $s.WorkingDirectory = $env:FINAPPGO_DIR; $s.IconLocation = (Join-Path $env:FINAPPGO_DIR 'app\web\finappgo.ico') + ',0'; $s.Description = 'FinAppGo: tu patrimonio'; $s.Save()"
if errorlevel 1 (
  echo.
  echo  No he podido crear el acceso directo. Puedes hacerlo a mano: clic derecho
  echo  sobre Iniciar.bat, "Enviar a" y "Escritorio (crear acceso directo)".
) else (
  echo.
  echo  Listo: tienes el icono "FinAppGo" en tu Escritorio. Abrelo con doble clic.
)
if not defined FINAPPGO_ESCRITORIO pause
