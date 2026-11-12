' 脱离启动模板：绕开 shell 执行器抖动 / 会话回收，长跑任务用这个拉起。
' 用法：cscript //nologo launch.vbs <脚本名.py>（在 scripts 目录内跑，日志落 <XDL_ROOT>\<脚本名>.log）
' 需要先 set TARGET_SCREEN_NAME / XDL_ROOT 等环境变量（cmd 的 set 在 /c 子进程里生效）
Dim args, shell, cmd
Set args = WScript.Arguments
If args.Count < 1 Then
  WScript.Echo "usage: cscript //nologo launch.vbs <script.py> [env: K=V ...]"
  WScript.Quit 2
End If

Dim scriptName, envPart, i
scriptName = args(0)
envPart = ""
For i = 1 To args.Count - 1
  envPart = envPart & "set " & args(i) & " && "
Next

Dim fso, root
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))

' XDL_ROOT 默认值由脚本自己处理；这里只传用户给的 env
cmd = "cmd /c cd /d " & root & "\scripts && " & envPart & _
      root & "\scripts\.venv\python.exe -u " & scriptName & _
      " > " & root & "\scripts\" & scriptName & ".log 2>&1"

CreateObject("WScript.Shell").Run cmd, 0, False
