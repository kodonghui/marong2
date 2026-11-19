param([Parameter(Mandatory = $true)][string]$Output)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$lines = Get-Content -Raw -Encoding utf8 (Join-Path $PSScriptRoot 'lines.json') | ConvertFrom-Json
$directory = New-Item -Type Directory -Path $Output -Force
$reader = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice = $reader.GetInstalledVoices() |
        Where-Object { $_.VoiceInfo.Culture.Name -eq 'ko-KR' -and $_.Enabled } |
        Select-Object -First 1
    if (-not $voice) { throw '한국어 합성 음성이 필요합니다.' }
    $reader.SelectVoice($voice.VoiceInfo.Name)
    $mono = [System.Speech.AudioFormat.AudioChannel]::Mono
    $sixteen = [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(16000, $sixteen, $mono)
    foreach ($line in $lines) {
        $target = Join-Path $directory.FullName ('{0:000}.wav' -f [int]$line.second)
        $reader.SetOutputToWaveFile($target, $format)
        $reader.Speak($line.text)
        $reader.SetOutputToNull()
    }
} finally {
    $reader.Dispose()
}
