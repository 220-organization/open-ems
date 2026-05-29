#!/usr/bin/env python3
"""Regenerate favicon / Android / iOS icons from ui/public/static/220-km-logo.svg (220-km pink brand)."""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / 'ui/public/static/220-km-logo.svg'
STATIC = ROOT / 'ui/public/static'
ANDROID_RES = ROOT / 'app-mobile/android/app/src/main/res'
IOS_ICON = ROOT / 'app-mobile/ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png'
BRAND_BG = (20, 20, 20, 255)  # #141414 — matches 220-km logo disc


def render_svg_to_png(svg_path: Path, png_path: Path, size: int) -> None:
    if platform.system() == 'Darwin' and shutil.which('qlmanage'):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            subprocess.run(
                ['qlmanage', '-t', '-s', str(size), '-o', str(out), str(svg_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            thumb = out / f'{svg_path.name}.png'
            if not thumb.exists():
                raise RuntimeError(f'qlmanage did not produce {thumb}')
            shutil.copy(thumb, png_path)
        return
    if shutil.which('rsvg-convert'):
        subprocess.run(
            ['rsvg-convert', '-w', str(size), '-h', str(size), '-o', str(png_path), str(svg_path)],
            check=True,
        )
        return
    raise SystemExit('Need qlmanage (macOS) or rsvg-convert to render SVG icons')


def main() -> None:
    if not SVG.exists():
        raise SystemExit(f'Missing source logo: {SVG}')

    master = STATIC / 'open-ems-icon-source.png'
    render_svg_to_png(SVG, master, 1024)
    icon = Image.open(master).convert('RGBA')

    for name, size in {
        'favicon-32.png': 32,
        'favicon-16.png': 16,
        'apple-touch-icon.png': 180,
        'open-ems-og.png': 512,
        'open-ems-icon.png': 1024,
    }.items():
        icon.resize((size, size), Image.Resampling.LANCZOS).save(STATIC / name)

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
        icon.resize((launcher, launcher), Image.Resampling.LANCZOS).save(d / 'ic_launcher.png')
        icon.resize((launcher, launcher), Image.Resampling.LANCZOS).save(d / 'ic_launcher_round.png')
        fg_img = Image.new('RGBA', (fg, fg), (0, 0, 0, 0))
        inner = int(fg * 0.82)
        inner_img = icon.resize((inner, inner), Image.Resampling.LANCZOS)
        offset = (fg - inner) // 2
        fg_img.paste(inner_img, (offset, offset), inner_img)
        fg_img.save(d / 'ic_launcher_foreground.png')

    icon.resize((1024, 1024), Image.Resampling.LANCZOS).save(IOS_ICON)

    # Keep in-app SVG alias in sync
    alias = STATIC / 'open-ems-220-logo.svg'
    alias.write_bytes(SVG.read_bytes())

    print('220-km pink brand icons regenerated from', SVG)


if __name__ == '__main__':
    main()
