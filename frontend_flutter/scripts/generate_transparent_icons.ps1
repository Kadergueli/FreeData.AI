$csFile = "C:\Users\Meroo\.gemini\antigravity\brain\598d71e4-7bde-4188-be36-972ddbacf99d\scratch\IconProcessor.cs"
Add-Type -Path $csFile -ReferencedAssemblies System.Drawing

$srcPath = "C:\Users\Meroo\.gemini\antigravity\brain\598d71e4-7bde-4188-be36-972ddbacf99d\.user_uploaded\media_1794536987667_db9dedee.jpg"
$bmp = New-Object System.Drawing.Bitmap($srcPath)

# 1. Remove background with high quality alpha matte
$transparentFull = [IconProcessor]::RemoveBackground($bmp, $false)

# 2. Crop centered 780 x 780 square
$cropSize = 780
$cropX = 72
$cropY = 135

$masterSquare = New-Object System.Drawing.Bitmap($cropSize, $cropSize, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($masterSquare)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
$g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
$g.Clear([System.Drawing.Color]::Transparent)

$destRect = New-Object System.Drawing.Rectangle(0, 0, $cropSize, $cropSize)
$g.DrawImage($transparentFull, $destRect, $cropX, $cropY, $cropSize, $cropSize, [System.Drawing.GraphicsUnit]::Pixel)
$g.Dispose()

# 3. High quality scaling function preserving 32-bit ARGB transparency
function Save-Transparent-Scaled([System.Drawing.Bitmap]$source, [int]$size, [string]$outPath) {
    $dir = Split-Path -Parent $outPath
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $target = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $tg = [System.Drawing.Graphics]::FromImage($target)
    $tg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $tg.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $tg.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $tg.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $tg.Clear([System.Drawing.Color]::Transparent)
    $tg.DrawImage($source, 0, 0, $size, $size)
    $tg.Dispose()
    $target.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $target.Dispose()
    Write-Output "Generated transparent icon: $size x $size -> $outPath"
}

$webDir = "d:\freedata-ai\frontend_flutter\web"
$buildWebDir = "d:\freedata-ai\frontend_flutter\build\web"

# Save to web/
Save-Transparent-Scaled $masterSquare 512 "$webDir\favicon.png"
Save-Transparent-Scaled $masterSquare 512 "$webDir\icons\Icon-512.png"
Save-Transparent-Scaled $masterSquare 512 "$webDir\icons\Icon-maskable-512.png"
Save-Transparent-Scaled $masterSquare 192 "$webDir\icons\Icon-192.png"
Save-Transparent-Scaled $masterSquare 192 "$webDir\icons\Icon-maskable-192.png"

# Save to build/web/
Save-Transparent-Scaled $masterSquare 512 "$buildWebDir\favicon.png"
Save-Transparent-Scaled $masterSquare 512 "$buildWebDir\icons\Icon-512.png"
Save-Transparent-Scaled $masterSquare 512 "$buildWebDir\icons\Icon-maskable-512.png"
Save-Transparent-Scaled $masterSquare 192 "$buildWebDir\icons\Icon-192.png"
Save-Transparent-Scaled $masterSquare 192 "$buildWebDir\icons\Icon-maskable-192.png"

# Also save a 64x64 and 32x32 for test/inspection in scratch
Save-Transparent-Scaled $masterSquare 64 "C:\Users\Meroo\.gemini\antigravity\brain\598d71e4-7bde-4188-be36-972ddbacf99d\scratch\favicon_64.png"
Save-Transparent-Scaled $masterSquare 32 "C:\Users\Meroo\.gemini\antigravity\brain\598d71e4-7bde-4188-be36-972ddbacf99d\scratch\favicon_32.png"

$masterSquare.Dispose()
$transparentFull.Dispose()
$bmp.Dispose()

Write-Output "All transparent icons generated successfully!"

