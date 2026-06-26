import { useEffect, useState } from 'react';
import { createPortStickerQrDataUrl } from './portStickerQr';

/** StartPage port-sticker QR — dark dots + rounded finder eyes on white. */
export default function PortStickerQrImage({
  url,
  size = 200,
  color = '#111111',
  className = '',
  alt = '',
}) {
  const [src, setSrc] = useState('');

  useEffect(() => {
    if (!url) {
      setSrc('');
      return undefined;
    }

    let active = true;
    try {
      const dataUrl = createPortStickerQrDataUrl(url, { size, color, background: '#ffffff' });
      if (active) setSrc(dataUrl);
    } catch {
      if (active) setSrc('');
    }

    return () => {
      active = false;
    };
  }, [url, size, color]);

  if (!src) return null;

  return (
    <img
      src={src}
      width={size}
      height={size}
      alt={alt}
      className={className}
      decoding="async"
      loading="lazy"
    />
  );
}
