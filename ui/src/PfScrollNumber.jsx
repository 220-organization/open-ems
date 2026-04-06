import { motion, AnimatePresence } from 'framer-motion';
import styles from './pf-scroll-number.module.css';

/**
 * Vertical slide + fade when `children` (formatted number) changes — same behavior as
 * src-js/react/src/shared/ui/scroll-number (B2bLanding user counter).
 */
export default function PfScrollNumber({
  direction = 'up',
  duration = 0.32,
  ease = [0.33, 0, 0.2, 1],
  children,
  className,
  numberStyle,
  ...props
}) {
  return (
    <div className={styles.container} {...props}>
      <AnimatePresence>
        <motion.span
          className={className}
          style={{
            ...numberStyle,
          }}
          key={children}
          exit={{
            y: direction === 'up' ? -10 : 20,
            opacity: 0,
            position: 'absolute',
          }}
          initial={{
            y: direction === 'up' ? 20 : -10,
            opacity: 0,
            position: 'absolute',
          }}
          animate={{ y: 0, opacity: 1 }}
          transition={{
            ease,
            duration,
          }}
        >
          {children}
        </motion.span>
      </AnimatePresence>
    </div>
  );
}
