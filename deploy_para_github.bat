@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM =============================================================================
REM Copia SOURCE para REPO + git add, commit, push (Abobi Server Cron / ServidorCron)
REM GitHub: https://github.com/abobicaduco/ServidorCron
REM
REM Modos:
REM   A) REPO = SOURCE (mesma pasta): so commit/push — padrao abaixo.
REM   B) REPO = outro clone: copia arquivos do SOURCE para o clone e depois push.
REM Primeira vez neste PC: git config --global user.name "Seu Nome"
REM                         git config --global user.email "email@exemplo.com"
REM Nesta pasta sem .git ainda:
REM   git init -b main
REM   git remote add origin https://github.com/abobicaduco/ServidorCron.git
REM =============================================================================

set "SOURCE=g:\My Drive\python\AbobiServerCron"
REM Mesma pasta do projeto = deploy direto (sem copia). Troque se usar clone em outro disco:
set "REPO=%SOURCE%"
REM Exemplo clone separado: set "REPO=D:\git\ServidorCron"

REM Push FORCADO: substitui a branch main no GitHub por esta pasta ^(apaga historico antigo no remoto^).
REM ATENCAO: depois que o push funcionar UMA vez, COMENTE a linha abaixo para nao sobrescrever o GitHub por engano.
set "FORCE_GITHUB=1"
REM Para deploy normal ^(sem apagar historico remoto^): comente a linha acima com REM.

REM Opcional: usar sempre a pasta onde esta o .bat
REM set "SOURCE=%~dp0" & if "%SOURCE:~-1%"=="\" set "SOURCE=%SOURCE:~0,-1%" & set "REPO=%SOURCE%"

if not exist "%REPO%\.git" (
  echo [ERRO] Pasta sem repositorio git: %REPO%
  echo.
  echo Rode nesta pasta ^(uma vez^):
  echo   git init -b main
  echo   git remote add origin https://github.com/abobicaduco/ServidorCron.git
  echo Se o remoto ja tiver historico: git pull origin main --allow-unrelated-histories
  echo Depois: git push -u origin main
  exit /b 1
)
if not exist "%SOURCE%\main.py" (
  echo [ERRO] SOURCE invalida ^(esperado main.py^): %SOURCE%
  exit /b 1
)

echo SOURCE: %SOURCE%
echo REPO:   %REPO%
echo.

if /I "%SOURCE%"=="%REPO%" goto SAME_FOLDER

echo A copiar para o clone...
for %%F in (main.py dashboard.html README.md LICENSE requirements.txt .gitignore .env.example deploy_para_github.bat.example) do (
  if exist "%SOURCE%\%%F" (
    copy /Y "%SOURCE%\%%F" "%REPO%\%%F" >nul
    echo   OK %%F
  )
)
if exist "%SOURCE%\deploy_para_github.bat" (
  copy /Y "%SOURCE%\deploy_para_github.bat" "%REPO%\deploy_para_github.bat" >nul
  echo   OK deploy_para_github.bat
)
if exist "%SOURCE%\automacoes" (
  if not exist "%REPO%\automacoes" mkdir "%REPO%\automacoes"
  robocopy "%SOURCE%\automacoes" "%REPO%\automacoes" /E /NFL /NDL /NJH /NJS
  if errorlevel 8 (
    echo [ERRO] robocopy automacoes
    exit /b 1
  )
  echo   OK automacoes\
)
goto DO_GIT

:SAME_FOLDER
echo [INFO] SOURCE e REPO iguais - sem copia, so git.

:DO_GIT
echo.
echo --- Git ---
pushd "%REPO%"

git add main.py dashboard.html README.md LICENSE requirements.txt .gitignore .env.example 2>nul
git add deploy_para_github.bat deploy_para_github.bat.example 2>nul
git add automacoes 2>nul
git add -A
git status

REM git diff --staged --quiet: codigo 0 = nada a commitar, 1 = ha alteracoes
git diff --staged --quiet
if errorlevel 1 (
  git commit -m "chore: sync Abobi Server Cron"
  if errorlevel 1 (
    echo [ERRO] git commit falhou. Veja a mensagem acima.
    echo        Se aparecer "Author identity unknown", rode:
    echo        git config user.name "Seu Nome"
    echo        git config user.email "seu@email.com"
    popd
    exit /b 1
  )
  echo [OK] Commit criado.
) else (
  echo [INFO] Nenhuma alteracao para commitar — continuando ^(push pode dizer "Already up to date"^).
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
  echo [ERRO] Remote "origin" nao existe. Rode:
  echo   git remote add origin https://github.com/abobicaduco/ServidorCron.git
  popd
  exit /b 1
)

if defined FORCE_GITHUB (
  echo [AVISO] Push FORCADO — main local substitui a main no GitHub.
  git push -u origin main --force
) else (
  git push -u origin main
)
set ERR=!ERRORLEVEL!
popd

if not "!ERR!"=="0" (
  echo [ERRO] git push falhou.
  exit /b 1
)
echo [OK] Push concluido no GitHub ^(branch main, upstream origin/main^).
exit /b 0
