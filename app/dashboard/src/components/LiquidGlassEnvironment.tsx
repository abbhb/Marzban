import { usePrefersReducedMotion } from "@chakra-ui/react";
import { ReactNode, useEffect, useRef } from "react";

type LiquidGlassEnvironmentProps = {
  children: ReactNode;
};

/**
 * Shares one light source across every glass surface, including Chakra portals.
 * The values live on <html>, so menus, drawers and dialogs reflect the same
 * environment instead of behaving like unrelated translucent cards.
 */
export const LiquidGlassEnvironment = ({
  children,
}: LiquidGlassEnvironmentProps) => {
  const reduceMotion = usePrefersReducedMotion();
  const animationFrame = useRef<number | null>(null);
  const pendingPosition = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const root = document.documentElement;
    const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");

    const reset = () => {
      root.style.setProperty("--liquid-env-x", "68%");
      root.style.setProperty("--liquid-env-y", "18%");
      root.style.setProperty("--liquid-env-shift-x", "0px");
      root.style.setProperty("--liquid-env-shift-y", "0px");
      root.style.setProperty("--liquid-env-shift-x-soft", "0px");
      root.style.setProperty("--liquid-env-shift-y-soft", "0px");
      root.style.setProperty("--liquid-env-shift-x-inverse", "0px");
      root.style.setProperty("--liquid-env-shift-y-inverse", "0px");
      root.dataset.liquidEnvironmentActive = "false";
    };

    if (reduceMotion || !finePointer.matches) {
      reset();
      return undefined;
    }

    const flush = () => {
      animationFrame.current = null;
      const position = pendingPosition.current;
      if (!position) return;

      root.style.setProperty("--liquid-env-x", `${position.x}%`);
      root.style.setProperty("--liquid-env-y", `${position.y}%`);
      root.style.setProperty(
        "--liquid-env-shift-x",
        `${((position.x - 50) / 50) * 9}px`
      );
      root.style.setProperty(
        "--liquid-env-shift-y",
        `${((position.y - 50) / 50) * 7}px`
      );
      root.style.setProperty(
        "--liquid-env-shift-x-soft",
        `${((position.x - 50) / 50) * 3}px`
      );
      root.style.setProperty(
        "--liquid-env-shift-y-soft",
        `${((position.y - 50) / 50) * 2.5}px`
      );
      root.style.setProperty(
        "--liquid-env-shift-x-inverse",
        `${((50 - position.x) / 50) * 3}px`
      );
      root.style.setProperty(
        "--liquid-env-shift-y-inverse",
        `${((50 - position.y) / 50) * 2.5}px`
      );
      root.dataset.liquidEnvironmentActive = "true";
    };

    const update = (event: PointerEvent) => {
      if (event.pointerType === "touch") return;
      const x = Math.max(
        0,
        Math.min(100, (event.clientX / window.innerWidth) * 100)
      );
      const y = Math.max(
        0,
        Math.min(100, (event.clientY / window.innerHeight) * 100)
      );
      pendingPosition.current = { x, y };
      if (animationFrame.current === null) {
        animationFrame.current = window.requestAnimationFrame(flush);
      }
    };

    window.addEventListener("pointermove", update, { passive: true });
    window.addEventListener("blur", reset);
    reset();

    return () => {
      window.removeEventListener("pointermove", update);
      window.removeEventListener("blur", reset);
      if (animationFrame.current !== null) {
        window.cancelAnimationFrame(animationFrame.current);
      }
      pendingPosition.current = null;
    };
  }, [reduceMotion]);

  return <>{children}</>;
};
