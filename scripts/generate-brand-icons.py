#!/usr/bin/env python3
"""Regenerate favicon / Android / iOS icons from ui/public/static/open-ems-logo.png."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'ui/public/static/open-ems-logo.png'
STATIC = ROOT / 'ui/public/static'
ANDROID_RES = ROOT / 'app-mobile/android/app/src/main/res'
IOS_ICON = ROOT / 'app-mobile/ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png'


def crop_icon(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, int(h * 0.78))
    left = (w - side) // 2
    return img.crop((left, 0, left + side, side))


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f'Missing source logo: {SRC}')
    img = Image.open(SRC).convert('RGBA')
    icon = crop_icon(img)

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
        inner = int(fg * 0.72)
        inner_img = icon.resize((inner, inner), Image.Resampling.LANCZOS)
        offset = (fg - inner) // 2
        fg_img.paste(inner_img, (offset, offset), inner_img)
        fg_img.save(d / 'ic_launcher_foreground.png')

    icon.resize((1024, 1024), Image.Resampling.LANCZOS).save(IOS_ICON)
    print('Brand icons regenerated.')


if __name__ == '__main__':
    main()
