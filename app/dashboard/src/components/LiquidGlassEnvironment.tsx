import { ReactNode } from "react";

type LiquidGlassEnvironmentProps = {
  children: ReactNode;
};

/**
 * Keeps the glass system scoped behind one provider without turning the whole
 * interface into a pointer-reactive surface. Large interactive cards can opt
 * into their own local highlight through `LiquidSurface`; ordinary controls,
 * menus and navigation remain visually stable.
 */
export const LiquidGlassEnvironment = ({
  children,
}: LiquidGlassEnvironmentProps) => <>{children}</>;
