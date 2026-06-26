#!/usr/bin/env python3
"""Regenerate favicon / PWA / Android / iOS icons from ui/public/static/vyriy-ems-logo.svg."""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / 'ui/public/static/vyriy-ems-logo.svg'
STATIC = ROOT / 'ui/public/static'
PWA_DIR = STATIC / 'pwa'
ANDROID_RES = ROOT / 'app-mobile/android/app/src/main/res'
IOS_ICON = ROOT / 'app-mobile/ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png'
BRAND_BG = (20, 20, 20, 255)  # #141414 — matches PWA theme_color


def render_svg_to_png(svg_path: Path, png_path: Path, size: int) -> None:
    svg_text = svg_path.read_text(encoding='utf-8')
    # Force the rasterizer to fill the output canvas (qlmanage ignores tiny width/height attrs).
    scaled_svg = svg_text.replace('width="30"', f'width="{size}"', 1).replace(
        'height="30"', f'height="{size}"', 1
    )
    with tempfile.NamedTemporaryFile('w', suffix='.svg', delete=False, encoding='utf-8') as tmp_svg:
        tmp_svg.write(scaled_svg)
        tmp_svg_path = Path(tmp_svg.name)

    try:
        if platform.system() == 'Darwin' and shutil.which('qlmanage'):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                subprocess.run(
                    ['qlmanage', '-t', '-s', str(size), '-o', str(out), str(tmp_svg_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                thumb = out / f'{tmp_svg_path.name}.png'
                if not thumb.exists():
                    raise RuntimeError(f'qlmanage did not produce {thumb}')
                shutil.copy(thumb, png_path)
            return
        if shutil.which('rsvg-convert'):
            subprocess.run(
                ['rsvg-convert', '-w', str(size), '-h', str(size), '-o', str(png_path), str(tmp_svg_path)],
                check=True,
            )
            return
        raise SystemExit('Need qlmanage (macOS) or rsvg-convert to render SVG icons')
    finally:
        tmp_svg_path.unlink(missing_ok=True)


def remove_white_background(img: Image.Image) -> Image.Image:
    rgba = img.convert('RGBA')
    pixels = rgba.load()
    width, height = rgba.size
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if red > 250 and green > 250 and blue > 250:
                pixels[x, y] = (255, 255, 255, 0)
    return rgba


def crop_to_content(img: Image.Image) -> Image.Image:
    """Trim empty/white padding from rasterized SVG (qlmanage fills canvas with white)."""
    rgba = img.convert('RGBA')
    pixels = rgba.load()
    width, height = rgba.size
    min_x, min_y = width, height
    max_x, max_y = -1, -1

    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha < 16:
                continue
            if red > 250 and green > 250 and blue > 250:
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

    if max_x < 0:
        raise RuntimeError('Logo render is empty')

    return rgba.crop((min_x, min_y, max_x + 1, max_y + 1))


def composite_icon(logo: Image.Image, size: int, logo_scale: float) -> Image.Image:
    """Place the logo centered on brand background; logo_scale is fraction of canvas width."""
    canvas = Image.new('RGBA', (size, size), BRAND_BG)
    inner = max(1, int(size * logo_scale))
    inner_img = logo.resize((inner, inner), Image.Resampling.LANCZOS)
    offset = (size - inner) // 2
    canvas.paste(inner_img, (offset, offset), inner_img)
    return canvas


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert('RGBA').save(path, optimize=True)


def main() -> None:
    if not SVG.exists():
        raise SystemExit(f'Missing source logo: {SVG}')

    master = STATIC / 'open-ems-icon-source.png'
    render_svg_to_png(SVG, master, 1024)
    logo = crop_to_content(remove_white_background(Image.open(master).convert('RGBA')))

    # Home screen / PWA icons — logo ~72% on dark disc (crisp on iOS + Android).
    pwa_any_scale = 0.72
    pwa_maskable_scale = 0.52  # Android maskable safe zone (~80% diameter circle)

    pwa_icons = {
        'icon-48.png': 48,
        'icon-72.png': 72,
        'icon-96.png': 96,
        'icon-128.png': 128,
        'icon-120.png': 120,
        'icon-144.png': 144,
        'icon-152.png': 152,
        'icon-167.png': 167,
        'icon-180.png': 180,
        'icon-192.png': 192,
        'icon-256.png': 256,
        'icon-384.png': 384,
        'icon-512.png': 512,
    }
    for name, size in pwa_icons.items():
        save_png(composite_icon(logo, size, pwa_any_scale), PWA_DIR / name)

    save_png(
        composite_icon(logo, 512, pwa_maskable_scale),
        PWA_DIR / 'icon-512-maskable.png',
    )

    # Legacy paths referenced by HTML / OG tags.
    save_png(composite_icon(logo, 32, pwa_any_scale), STATIC / 'favicon-32.png')
    save_png(composite_icon(logo, 16, pwa_any_scale), STATIC / 'favicon-16.png')
    save_png(composite_icon(logo, 180, pwa_any_scale), STATIC / 'apple-touch-icon.png')
    save_png(composite_icon(logo, 512, pwa_any_scale), STATIC / 'open-ems-og.png')
    save_png(composite_icon(logo, 1024, pwa_any_scale), STATIC / 'open-ems-icon.png')

    android = {
        'mipmap-mdpi': (48, 108),
        'mipmap-hdpi': (72, 162),
        'mipmap-xhdpi': (96, 216),
        'mipmap-xxhdpi': (144, 324),
        'mipmap-xxxhdpi': (192, 432),
    }
    for folder, (launcher, fg) in android.items():
        d = ANDROID_RES / folder
        d.mkdir(parents=True, exist_ok=True)
        launcher_img = composite_icon(logo, launcher, pwa_any_scale)
        save_png(launcher_img, d / 'ic_launcher.png')
        save_png(launcher_img, d / 'ic_launcher_round.png')
        fg_img = Image.new('RGBA', (fg, fg), (0, 0, 0, 0))
        inner = int(fg * pwa_maskable_scale)
        inner_img = logo.resize((inner, inner), Image.Resampling.LANCZOS)
        offset = (fg - inner) // 2
        fg_img.paste(inner_img, (offset, offset), inner_img)
        save_png(fg_img, d / 'ic_launcher_foreground.png')

    save_png(composite_icon(logo, 1024, pwa_any_scale), IOS_ICON)

    print('Open EMS brand icons regenerated from', SVG)
    print('PWA icons:', PWA_DIR)


if __name__ == '__main__':
    main()
