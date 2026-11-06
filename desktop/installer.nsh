!macro customCheckAppRunning
  ; Stop the previous app before the default NSIS running-app check can prompt.
  nsExec::ExecToLog 'taskkill /F /T /IM MythicalAge.exe'
  nsExec::ExecToLog 'taskkill /F /T /IM mythical-backend.exe'
  Sleep 1000
!macroend

!macro customUnInstallCheck
  ClearErrors
  StrCpy $R0 0
!macroend

!macro customUnInstallCheckCurrentUser
  ClearErrors
  StrCpy $R0 0
!macroend
