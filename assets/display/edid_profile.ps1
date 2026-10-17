param([Parameter(Mandatory=$true)][string]$Request)
$ErrorActionPreference='Stop'
$requestPath=[IO.Path]::GetFullPath($Request)
$job=Get-Content -LiteralPath $requestPath -Raw -Encoding UTF8|ConvertFrom-Json
if($job.version -ne 1 -or $job.action -notin @('on','off','restore')){throw 'Invalid display request'}
if($job.refresh -and $job.refresh -notin @('monitor','hdmi')){throw 'Invalid EDID refresh method'}
if($job.instance -notmatch '^DISPLAY\\XMI27B3\\[A-Za-z0-9&_-]+$'){throw 'Only an exact XMI27B3 instance is accepted'}
$reply=$requestPath+'.reply'
$decision=$requestPath+'.decision'
$lease=$requestPath+'.lease'
if((Test-Path -LiteralPath $decision) -and (Get-Content -LiteralPath $decision -Raw).Trim() -eq 'rollback'){throw 'Request was cancelled before elevation'}
$relative='SYSTEM\CurrentControlSet\Enum\'+$job.instance+'\Device Parameters'
$original='EDID_OVERRIDE_Mimonitor2025_Original'
$metadata='Mimonitor2025_Edid'
$temporary='EDID_OVERRIDE_Mimonitor2025_Transaction_'+[guid]::NewGuid().ToString('N')
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if(!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator token required'}
Add-Type @'
using System;using System.Runtime.InteropServices;
public static class ToolboxEdidRegistry {
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode)] public static extern int RegRenameKey(IntPtr key,string oldName,string newName);
}
'@
function Reply($phase,$detail){
 $data=[ordered]@{phase=$phase;detail=$detail;token=$job.token}
 $data|ConvertTo-Json -Compress|Set-Content -LiteralPath ($reply+'.tmp') -Encoding UTF8
 Move-Item -LiteralPath ($reply+'.tmp') -Destination $reply -Force
}
function Rename($from,$to){
 $result=[ToolboxEdidRegistry]::RegRenameKey($parent.Handle.DangerousGetHandle(),$from,$to)
 if($result -ne 0){throw "Registry rename failed: $result"}
}
function Read-Values($key){
 $result=@{}
 if($key){foreach($name in $key.GetValueNames()){
  if($key.GetValueKind($name) -ne [Microsoft.Win32.RegistryValueKind]::Binary){throw 'Unexpected EDID registry value type'}
  $result[$name]=[BitConverter]::ToString($key.GetValue($name)).Replace('-','').ToLowerInvariant()
 }}
 return $result
}
function Restart-Target {
 if($job.refresh -eq 'hdmi'){return}
 $null=& "$env:SystemRoot\System32\pnputil.exe" /restart-device $job.instance
 if($LASTEXITCODE -ne 0){throw "Monitor re-enumeration failed: $LASTEXITCODE"}
}
$parent=$null;$moved=$false;$restoredOriginal=$false;$createdActive=$false;$committed=$false;$changed=$false;$savedFirstOriginal=$false
$oldMeta=$null;$managed=$false;$hadActive=$false
try{
 $parent=[Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($relative,$true)
 if(!$parent){throw 'Target monitor instance no longer exists'}
 [byte[]]$hardware=$parent.GetValue('EDID')
 if($hardware.Length -lt 128 -or [BitConverter]::ToString($hardware[8..11]) -ne '61-A9-B3-27'){throw 'Target EDID identity changed'}
 $active=$parent.OpenSubKey('EDID_OVERRIDE')
 $hadActive=$null -ne $active
 $values=Read-Values $active
 if($active){$active.Close()}
 $expected=@{}
 foreach($entry in $job.expected.PSObject.Properties){$expected[$entry.Name]=[string]$entry.Value}
 if($values.Count -ne $expected.Count){throw 'EDID changed while requesting elevation'}
 foreach($name in $values.Keys){if(!$expected.ContainsKey($name) -or $values[$name] -cne $expected[$name]){throw 'EDID changed while requesting elevation'}}
 $meta=$parent.OpenSubKey($metadata)
 if($meta){
  $oldMeta=@{};foreach($name in $meta.GetValueNames()){$oldMeta[$name]=$meta.GetValue($name)}
  $managed=$meta.GetValue('Version') -eq 1
  $meta.Close()
  if(!$managed){throw 'Unrecognized managed EDID version'}
 }
 $hasOriginal=$parent.GetSubKeyNames() -contains $original
 if(!$managed -and $hasOriginal){throw 'An earlier EDID restore needs attention'}
 if($managed -and ([bool]$oldMeta.OriginalPresent -ne $hasOriginal)){throw 'Saved original EDID is missing or inconsistent'}
 if($job.action -eq 'restore' -and !$managed){Reply 'committed' 'Original configuration already active';$committed=$true;return}
 $changed=$true
 if($hadActive){Rename 'EDID_OVERRIDE' $temporary;$moved=$true}
 if($job.action -eq 'on'){
  [byte[]]$bytes=for($i=0;$i -lt $job.profile.Length;$i+=2){[Convert]::ToByte($job.profile.Substring($i,2),16)}
  if($bytes.Length -ne 384 -or [BitConverter]::ToString($bytes[8..11]) -ne '61-A9-B3-27'){throw 'Invalid compatible profile'}
  for($block=0;$block -lt 3;$block++){
   $sum=0;for($i=0;$i -lt 128;$i++){$sum+=$bytes[$block*128+$i]}
   if(($sum%256) -ne 0){throw 'Invalid EDID checksum'}
  }
  $active=$parent.CreateSubKey('EDID_OVERRIDE');$createdActive=$true
  try{for($block=0;$block -lt 3;$block++){$active.SetValue([string]$block,[byte[]]$bytes[($block*128)..($block*128+127)],[Microsoft.Win32.RegistryValueKind]::Binary)}}finally{$active.Close()}
 }elseif($job.action -eq 'restore' -and $hasOriginal){
  Rename $original 'EDID_OVERRIDE';$restoredOriginal=$true
 }
 Restart-Target
 Reply 'applied' 'Waiting for signal verification'
 # Restore the registry before the monitor's 16-second HDMI recovery fires.
 $deadline=[DateTime]::UtcNow.AddSeconds(10)
 while($true){
  if(Test-Path -LiteralPath $decision){
   $choice=(Get-Content -LiteralPath $decision -Raw).Trim()
   if($choice -eq 'commit'){break}
   throw 'Display verification requested rollback'
  }
  if(Test-Path -LiteralPath $lease){
   $updated=(Get-Item -LiteralPath $lease).LastWriteTimeUtc.AddSeconds(10)
   if($updated -gt $deadline){$deadline=$updated}
  }
  if([DateTime]::UtcNow -gt $deadline){throw 'Display verification timed out; restoring previous EDID'}
  Start-Sleep -Milliseconds 100
 }
 if($job.action -eq 'restore'){
  $parent.DeleteSubKeyTree($metadata,$false)
 }else{
  if(!$managed -and $moved){Rename $temporary $original;$moved=$false;$savedFirstOriginal=$true}
  $meta=$parent.CreateSubKey($metadata)
  try{
   $meta.SetValue('Version',1,[Microsoft.Win32.RegistryValueKind]::DWord)
   $meta.SetValue('OriginalPresent',[int]$(if($managed){$oldMeta.OriginalPresent}else{$hadActive}),[Microsoft.Win32.RegistryValueKind]::DWord)
   $meta.SetValue('Enabled',[int]($job.action -eq 'on'),[Microsoft.Win32.RegistryValueKind]::DWord)
   $meta.SetValue('Profile',[string]$job.profile,[Microsoft.Win32.RegistryValueKind]::String)
  }finally{$meta.Close()}
 }
 if($moved){$parent.DeleteSubKeyTree($temporary,$false);$moved=$false}
 $committed=$true
 Reply 'committed' 'Display configuration verified'
}catch{
 $failure=$_.Exception.Message
 if($parent -and $changed -and !$committed){
  try{
   if($restoredOriginal){Rename 'EDID_OVERRIDE' $original}
   elseif($createdActive){$parent.DeleteSubKeyTree('EDID_OVERRIDE',$false)}
   if($savedFirstOriginal){Rename $original 'EDID_OVERRIDE'}
   if($moved){Rename $temporary 'EDID_OVERRIDE';$moved=$false}
   $parent.DeleteSubKeyTree($metadata,$false)
   if($oldMeta){
    $meta=$parent.CreateSubKey($metadata)
    try{foreach($name in $oldMeta.Keys){$meta.SetValue($name,$oldMeta[$name])}}finally{$meta.Close()}
   }
   Restart-Target
   Reply 'rolled_back' $failure
  }catch{Reply 'recovery_failed' ($failure+'; '+$_.Exception.Message)}
 }else{Reply 'rejected' $failure}
 exit 1
}finally{
 if($parent){$parent.Close()}
}
