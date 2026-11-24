import { useCallback, useEffect, useRef, useState } from 'react';

const HOLD_MS = 2000;
const MOVE_PX = 16;

/**
 * Hold a control for 2 seconds, then run `onHold`.
 * A short click is left for the control's own click handler.
 */
export function useLongPressNavigate(onHold) {
  const timerRef = useRef(null);
  const originRef = useRef(null);
  const switchedRef = useRef(false);
  const [holding, setHolding] = useState(false);

  const clear = useCallback(() => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    originRef.current = null;
    setHolding(false);
  }, []);

  useEffect(
    () => () => {
      if (timerRef.current != null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    },
    []
  );

  const onPointerDown = useCallback(
    e => {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      clear();
      switchedRef.current = false;
      originRef.current = { x: e.clientX, y: e.clientY };
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        /* pointer capture is optional */
      }
      setHolding(true);
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        switchedRef.current = true;
        setHolding(false);
        onHold();
      }, HOLD_MS);
    },
    [clear, onHold]
  );

  const onPointerMove = useCallback(
    e => {
      const origin = originRef.current;
      if (!origin) return;
      if (Math.hypot(e.clientX - origin.x, e.clientY - origin.y) > MOVE_PX) clear();
    },
    [clear]
  );

  const consumeClick = useCallback(e => {
    if (!switchedRef.current) return false;
    e.preventDefault();
    e.stopPropagation();
    switchedRef.current = false;
    return true;
  }, []);

  return {
    holding,
    holdHandlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: clear,
      onPointerCancel: clear,
      onContextMenu: e => e.preventDefault(),
      onDragStart: e => e.preventDefault(),
    },
    consumeClick,
  };
}
