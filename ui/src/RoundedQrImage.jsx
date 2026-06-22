import { useEffect, useState } from 'react';
import { createRoundedQrDataUrl } from './roundedQr';

export default function RoundedQrImage({
  url,
  size = 256,
  color = '#ffffff',
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
    createRoundedQrDataUrl(url, { size, color })
      .then(dataUrl => {
        if (active) setSrc(dataUrl);
      })
      .catch(() => {
        if (active) setSrc('');
      });

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
