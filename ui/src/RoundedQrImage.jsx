import { useEffect, useState } from 'react';
import { createRoundedQrDataUrl, qrRenderPixelSize } from './roundedQr';

export default function RoundedQrImage({
  url,
  size = 256,
  color = '#000000',
  background = '#ffffff',
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
    const renderSize = qrRenderPixelSize(size);
    createRoundedQrDataUrl(url, { size: renderSize, color, background })
      .then(dataUrl => {
        if (active) setSrc(dataUrl);
      })
      .catch(() => {
        if (active) setSrc('');
      });

    return () => {
      active = false;
    };
  }, [url, size, color, background]);

  if (!src) return null;

  return (
    <img
      src={src}
      width={size}
      height={size}
      alt={alt}
      className={className}
      decoding="sync"
      loading={size <= 72 ? 'eager' : 'lazy'}
    />
  );
}
