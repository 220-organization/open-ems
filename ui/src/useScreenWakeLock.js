import { useEffect, useRef } from 'react';

/**
 * LG webOS / embedded TV browsers often lack Wake Lock or still dim/standby the panel.
 * A muted looping video fed by canvas.captureStream() is a common kiosk workaround.
 */
function isTvStyleUserAgent() {
  if (typeof navigator === 'undefined') return false;
  const ua = (navigator.userAgent || '').toLowerCase();
  return /web0?s|webos|webos\.tv|netcast|nettv|smart-tv|smarttv|hbbtv|maple|afts|aftb|aftm|crkey|googletv|appletv|tizen|livetv|tv\s*build|bravia|philips|hisense|chromiumtv|netrange|viera|dtv|hospitality|hotel/.test(
    ua
  );
}

function startKeepAlivePlayback() {
  if (typeof document === 'undefined') {
    return () => {};
  }

  const canvas = document.createElement('canvas');
  canvas.width = 16;
  canvas.height = 16;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    return () => {};
  }

  let stream;
  try {
    stream = canvas.captureStream(4);
  } catch {
    return () => {};
  }

  const video = document.createElement('video');
  video.muted = true;
  video.defaultMuted = true;
  video.setAttribute('muted', '');
  video.playsInline = true;
  video.setAttribute('playsinline', '');
  video.setAttribute('webkit-playsinline', '');
  video.loop = true;
  video.srcObject = stream;
  Object.assign(video.style, {
    position: 'fixed',
    left: '0',
    top: '0',
    width: '2px',
    height: '2px',
    opacity: '0',
    pointerEvents: 'none',
    zIndex: '0',
  });
  document.body.appendChild(video);

  let rafId = 0;
  const draw = () => {
    const t = (performance.now() / 80) | 0;
    ctx.fillStyle = t % 2 === 0 ? '#000000' : '#010101';
    ctx.fillRect(0, 0, 16, 16);
    rafId = requestAnimationFrame(draw);
  };
  draw();

  const play = () => {
    video.play().catch(() => {});
  };
  play();

  const onVisibility = () => {
    if (document.visibilityState === 'visible') {
      play();
    }
  };
  document.addEventListener('visibilitychange', onVisibility);

  return () => {
    cancelAnimationFrame(rafId);
    document.removeEventListener('visibilitychange', onVisibility);
    video.pause();
    try {
      stream.getTracks().forEach(tr => tr.stop());
    } catch {
      /* ignore */
    }
    video.srcObject = null;
    video.remove();
  };
}

/** Keeps the screen awake while kiosk / TV display is active. */
export function useScreenWakeLock(enabled) {
  const lockRef = useRef(null);
  const wakeLockFailedRef = useRef(false);

  useEffect(() => {
    if (!enabled) {
      wakeLockFailedRef.current = false;
      return undefined;
    }

    const tvStyle = isTvStyleUserAgent();
    const hasWakeLockApi = typeof navigator !== 'undefined' && typeof navigator.wakeLock?.request === 'function';

    let disposePlayback = () => {};
    let usePlayback = tvStyle || !hasWakeLockApi || wakeLockFailedRef.current;

    const ensurePlayback = () => {
      if (!usePlayback) return;
      disposePlayback();
      disposePlayback = startKeepAlivePlayback();
    };

    if (usePlayback) {
      ensurePlayback();
    }

    if (!hasWakeLockApi) {
      return () => {
        disposePlayback();
      };
    }

    let cancelled = false;

    const releaseCurrent = () => {
      const lock = lockRef.current;
      lockRef.current = null;
      if (lock && typeof lock.release === 'function') {
        lock.release().catch(() => {});
      }
    };

    const request = async () => {
      if (cancelled || typeof document === 'undefined' || document.visibilityState !== 'visible') {
        return;
      }
      try {
        releaseCurrent();
        const wl = await navigator.wakeLock.request('screen');
        if (cancelled) {
          wl.release().catch(() => {});
          return;
        }
        lockRef.current = wl;
      } catch {
        wakeLockFailedRef.current = true;
        usePlayback = true;
        ensurePlayback();
      }
    };

    request();

    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        request();
        if (usePlayback) {
          ensurePlayback();
        }
      } else {
        releaseCurrent();
      }
    };

    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisibility);
      releaseCurrent();
      disposePlayback();
    };
  }, [enabled]);
}
