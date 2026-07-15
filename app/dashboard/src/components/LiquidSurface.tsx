import {
  Box,
  BoxProps,
  forwardRef,
  usePrefersReducedMotion,
} from "@chakra-ui/react";
import { PointerEventHandler, useEffect, useRef } from "react";

export type LiquidSurfaceTone = "glass" | "strong" | "subtle";

export type LiquidSurfaceProps = BoxProps & {
  /** Enables the pointer-following highlight. It is opt-in so form panels stay still. */
  interactive?: boolean;
  /** Adds the small hover lift used by clickable cards. Defaults to `interactive`. */
  lift?: boolean;
  /** Controls the opacity and blur strength of the surface. */
  tone?: LiquidSurfaceTone;
};

const toneStyles: Record<
  LiquidSurfaceTone,
  { background: string; filter: string; shadow: string; darkShadow: string }
> = {
  glass: {
    background: "surface.glass",
    filter: "var(--marzban-glass-filter)",
    shadow: "glass.md",
    darkShadow: "glass.dark",
  },
  strong: {
    background: "surface.glass-strong",
    filter: "var(--marzban-glass-filter-strong)",
    shadow: "glass.lg",
    darkShadow: "glass.dark",
  },
  subtle: {
    background: "surface.muted",
    filter: "var(--marzban-glass-filter-subtle)",
    shadow: "glass-subtle",
    darkShadow: "glass-subtle-dark",
  },
};

export const LiquidSurface = forwardRef<LiquidSurfaceProps, "div">(
  (
    {
      children,
      className,
      interactive = false,
      lift = interactive,
      style,
      onPointerEnter,
      onPointerCancel,
      onPointerDown,
      onPointerLeave,
      onPointerMove,
      onPointerUp,
      tone = "glass",
      ...props
    },
    ref
  ) => {
    const reduceMotion = usePrefersReducedMotion();
    const animationFrame = useRef<number | null>(null);
    const pendingPosition = useRef<{
      element: HTMLDivElement;
      x: number;
      y: number;
    } | null>(null);
    const styles = toneStyles[tone];

    useEffect(
      () => () => {
        if (animationFrame.current !== null) {
          window.cancelAnimationFrame(animationFrame.current);
        }
      },
      []
    );

    const flushPointerPosition = () => {
      const pending = pendingPosition.current;
      animationFrame.current = null;
      if (!pending) return;
      pending.element.style.setProperty("--liquid-x", `${pending.x}%`);
      pending.element.style.setProperty("--liquid-y", `${pending.y}%`);
      pending.element.style.setProperty(
        "--liquid-tilt-x",
        `${((50 - pending.y) / 50) * 0.65}deg`
      );
      pending.element.style.setProperty(
        "--liquid-tilt-y",
        `${((pending.x - 50) / 50) * 0.8}deg`
      );
    };

    const handlePointerEnter: PointerEventHandler<HTMLDivElement> = (event) => {
      if (interactive && !reduceMotion && event.pointerType !== "touch") {
        event.currentTarget.dataset.liquidActive = "true";
      }
      onPointerEnter?.(event);
    };

    const handlePointerMove: PointerEventHandler<HTMLDivElement> = (event) => {
      if (interactive && !reduceMotion && event.pointerType !== "touch") {
        const bounds = event.currentTarget.getBoundingClientRect();
        if (bounds.width > 0 && bounds.height > 0) {
          const x = Math.max(
            0,
            Math.min(100, ((event.clientX - bounds.left) / bounds.width) * 100)
          );
          const y = Math.max(
            0,
            Math.min(100, ((event.clientY - bounds.top) / bounds.height) * 100)
          );
          pendingPosition.current = { element: event.currentTarget, x, y };
          if (animationFrame.current === null) {
            animationFrame.current =
              window.requestAnimationFrame(flushPointerPosition);
          }
        }
      }
      onPointerMove?.(event);
    };

    const handlePointerLeave: PointerEventHandler<HTMLDivElement> = (event) => {
      event.currentTarget.dataset.liquidActive = "false";
      event.currentTarget.dataset.liquidPressed = "false";
      pendingPosition.current = null;
      if (animationFrame.current !== null) {
        window.cancelAnimationFrame(animationFrame.current);
        animationFrame.current = null;
      }
      event.currentTarget.style.setProperty("--liquid-x", "76%");
      event.currentTarget.style.setProperty("--liquid-y", "-8%");
      event.currentTarget.style.setProperty("--liquid-tilt-x", "0deg");
      event.currentTarget.style.setProperty("--liquid-tilt-y", "0deg");
      onPointerLeave?.(event);
    };

    const handlePointerDown: PointerEventHandler<HTMLDivElement> = (event) => {
      if (interactive && !reduceMotion) {
        event.currentTarget.dataset.liquidPressed = "true";
      }
      onPointerDown?.(event);
    };

    const handlePointerUp: PointerEventHandler<HTMLDivElement> = (event) => {
      event.currentTarget.dataset.liquidPressed = "false";
      onPointerUp?.(event);
    };

    const handlePointerCancel: PointerEventHandler<HTMLDivElement> = (
      event
    ) => {
      event.currentTarget.dataset.liquidPressed = "false";
      onPointerCancel?.(event);
    };

    return (
      <Box
        ref={ref}
        position="relative"
        isolation="isolate"
        overflow="hidden"
        borderWidth="0"
        bg={styles.background}
        boxShadow={styles.shadow}
        backdropFilter={styles.filter}
        _dark={{ boxShadow: styles.darkShadow }}
        {...props}
        style={{ WebkitBackdropFilter: styles.filter, ...style }}
        className={[
          "liquid-surface",
          `liquid-surface--${tone}`,
          interactive ? "liquid-surface--interactive" : "",
          className || "",
        ]
          .filter(Boolean)
          .join(" ")}
        data-liquid-active="false"
        data-liquid-pressed="false"
        data-liquid-lift={
          interactive && lift && !reduceMotion ? "true" : undefined
        }
        onPointerEnter={interactive ? handlePointerEnter : onPointerEnter}
        onPointerMove={interactive ? handlePointerMove : onPointerMove}
        onPointerLeave={interactive ? handlePointerLeave : onPointerLeave}
        onPointerDown={interactive ? handlePointerDown : onPointerDown}
        onPointerUp={interactive ? handlePointerUp : onPointerUp}
        onPointerCancel={interactive ? handlePointerCancel : onPointerCancel}
      >
        {children}
      </Box>
    );
  }
);

LiquidSurface.displayName = "LiquidSurface";
