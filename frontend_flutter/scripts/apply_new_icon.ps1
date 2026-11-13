Add-Type -AssemblyName System.Drawing

$srcPath = "C:\Users\Meroo\.gemini\antigravity\brain\598d71e4-7bde-4188-be36-972ddbacf99d\.user_uploaded\media_1794536987667_db9dedee.jpg"
if (-not (Test-Path $srcPath)) {
    Write-Error "Source image not found at $srcPath"
    exit 1
}

$bmp = New-Object System.Drawing.Bitmap($srcPath)
Write-Output "Loaded source image: $($bmp.Width) x $($bmp.Height)"

# Crop centered on the icon (center 462, 526, size 860x860)
$cropSize = 860
$cropX = [int](462 - ($cropSize / 2))
$cropY = [int](526 - ($cropSize / 2))

$masterBmp = New-Object System.Drawing.Bitmap($cropSize, $cropSize)
$g = [System.Drawing.Graphics]::FromImage($masterBmp)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
$g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
$g.Clear([System.Drawing.Color]::White)

$destRect = New-Object System.Drawing.Rectangle(0, 0, $cropSize, $cropSize)
$g.DrawImage($bmp, $destRect, $cropX, $cropY, $cropSize, $cropSize, [System.Drawing.GraphicsUnit]::Pixel)
$g.Dispose()

function Save-Scaled([System.Drawing.Bitmap]$source, [int]$size, [string]$outPath) {
    $dir = Split-Path -Parent $outPath
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $target = New-Object System.Drawing.Bitmap($size, $size)
    $tg = [System.Drawing.Graphics]::FromImage($target)
    $tg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $tg.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $tg.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $tg.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $tg.Clear([System.Drawing.Color]::White)
    $tg.DrawImage($source, 0, 0, $size, $size)
    $tg.Dispose()
    $target.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $target.Dispose()
    Write-Output "Wrote $size x $size to $outPath"
}

$webDir = "d:\freedata-ai\frontend_flutter\web"
$buildWebDir = "d:\freedata-ai\frontend_flutter\build\web"

# Save to web/
Save-Scaled $masterBmp 512 "$webDir\favicon.png"
Save-Scaled $masterBmp 512 "$webDir\icons\Icon-512.png"
Save-Scaled $masterBmp 512 "$webDir\icons\Icon-maskable-512.png"
Save-Scaled $masterBmp 192 "$webDir\icons\Icon-192.png"
Save-Scaled $masterBmp 192 "$webDir\icons\Icon-maskable-192.png"

# Save to build/web/ if it exists
if (Test-Path $buildWebDir) {
    Save-Scaled $masterBmp 512 "$buildWebDir\favicon.png"
    Save-Scaled $masterBmp 512 "$buildWebDir\icons\Icon-512.png"
    Save-Scaled $masterBmp 512 "$buildWebDir\icons\Icon-maskable-512.png"
    Save-Scaled $masterBmp 192 "$buildWebDir\icons\Icon-192.png"
    Save-Scaled $masterBmp 192 "$buildWebDir\icons\Icon-maskable-192.png"
}

$masterBmp.Dispose()
$bmp.Dispose()

Write-Output "Icon generation complete!"

