param(
  [int]$Port = 8642
)

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot
python tools/yaml_studio.py --root examples --port $Port
