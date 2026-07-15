import { extendTheme } from "@chakra-ui/react";

const focusVisible = {
  outline: "2px solid",
  outlineColor: "focus.ring",
  outlineOffset: "2px",
  boxShadow: "none",
};

const ambientReflection = {
  position: "relative",
  isolation: "isolate",
  _before: {
    content: '""',
    position: "absolute",
    inset: "0",
    zIndex: "0",
    pointerEvents: "none",
    borderRadius: "inherit",
    bgImage:
      "radial-gradient(460px circle at var(--liquid-env-x) var(--liquid-env-y), rgba(255, 255, 255, 0.42), rgba(123, 196, 255, 0.12) 30%, transparent 68%), linear-gradient(128deg, rgba(255, 255, 255, 0.22), transparent 38%, rgba(96, 165, 250, 0.08) 74%, transparent)",
    opacity: 0.72,
    transform:
      "translate3d(var(--liquid-env-shift-x-soft), var(--liquid-env-shift-y-soft), 0)",
    transition:
      "transform var(--marzban-motion-slow) var(--marzban-ease-out), opacity var(--marzban-motion-base) ease",
  },
  "& > *": {
    position: "relative",
    zIndex: "1",
  },
};

export const theme = extendTheme({
  shadows: {
    outline: "0 0 0 3px rgba(38, 112, 232, 0.28)",
    glass: {
      md: "inset 0 1px 0 rgba(255, 255, 255, 0.72), inset 0 -1px 0 rgba(255, 255, 255, 0.12), 0 0 0 1px rgba(255, 255, 255, 0.40), 0 18px 48px rgba(31, 60, 105, 0.12)",
      lg: "inset 0 1px 0 rgba(255, 255, 255, 0.78), inset 0 -1px 0 rgba(255, 255, 255, 0.14), 0 0 0 1px rgba(255, 255, 255, 0.46), 0 24px 68px rgba(31, 60, 105, 0.16)",
      hover:
        "inset 0 1px 0 rgba(255, 255, 255, 0.84), inset 0 -1px 0 rgba(255, 255, 255, 0.16), 0 0 0 1px rgba(255, 255, 255, 0.54), 0 28px 76px rgba(31, 60, 105, 0.20)",
      dark: "inset 0 1px 0 rgba(255, 255, 255, 0.16), inset 0 -1px 0 rgba(255, 255, 255, 0.04), 0 0 0 1px rgba(255, 255, 255, 0.11), 0 20px 56px rgba(0, 0, 0, 0.32)",
      "dark-hover":
        "inset 0 1px 0 rgba(255, 255, 255, 0.20), inset 0 -1px 0 rgba(255, 255, 255, 0.05), 0 0 0 1px rgba(255, 255, 255, 0.15), 0 28px 72px rgba(0, 0, 0, 0.40)",
    },
    panel:
      "inset 0 1px 0 rgba(255, 255, 255, 0.62), 0 0 0 1px rgba(255, 255, 255, 0.34), 0 10px 32px rgba(31, 60, 105, 0.09)",
    "panel-dark":
      "inset 0 1px 0 rgba(255, 255, 255, 0.12), 0 0 0 1px rgba(255, 255, 255, 0.09), 0 12px 36px rgba(0, 0, 0, 0.26)",
    "glass-subtle":
      "inset 0 1px 0 rgba(255, 255, 255, 0.50), 0 0 0 1px rgba(71, 85, 105, 0.10)",
    "glass-subtle-dark":
      "inset 0 1px 0 rgba(255, 255, 255, 0.10), 0 0 0 1px rgba(255, 255, 255, 0.08)",
  },
  radii: {
    control: "12px",
    panel: "16px",
    glass: "20px",
  },
  fonts: {
    body: `-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", sans-serif`,
    heading: `-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", sans-serif`,
    mono: `"SFMono-Regular", "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace`,
  },
  colors: {
    "light-border": "rgba(71, 85, 105, 0.16)",
    primary: {
      50: "#eff6ff",
      100: "#dbeafe",
      200: "#bfdbfe",
      300: "#93c5fd",
      400: "#5b93f7",
      500: "#2670e8",
      600: "#1f5fcb",
      700: "#1d4ea5",
      800: "#1d4385",
      900: "#1c386b",
    },
    gray: {
      500: "#526079",
      750: "#222C3B",
    },
  },
  semanticTokens: {
    colors: {
      "app.canvas": { default: "#eaf1fa", _dark: "#080d16" },
      "surface.glass": {
        default: "rgba(255, 255, 255, 0.36)",
        _dark: "rgba(11, 18, 31, 0.50)",
      },
      "surface.glass-strong": {
        default: "rgba(255, 255, 255, 0.52)",
        _dark: "rgba(11, 18, 31, 0.66)",
      },
      "surface.panel": {
        default: "rgba(255, 255, 255, 0.48)",
        _dark: "rgba(18, 27, 43, 0.58)",
      },
      "surface.muted": {
        default: "rgba(241, 247, 255, 0.34)",
        _dark: "rgba(30, 41, 59, 0.34)",
      },
      "surface.input": {
        default: "rgba(255, 255, 255, 0.46)",
        _dark: "rgba(15, 23, 42, 0.48)",
      },
      "surface.inset": {
        default: "rgba(255, 255, 255, 0.24)",
        _dark: "rgba(15, 23, 42, 0.30)",
      },
      "surface.hover": {
        default: "rgba(38, 112, 232, 0.08)",
        _dark: "rgba(147, 197, 253, 0.10)",
      },
      "surface.active": {
        default: "rgba(38, 112, 232, 0.14)",
        _dark: "rgba(147, 197, 253, 0.16)",
      },
      "surface.track": {
        default: "rgba(100, 116, 139, 0.16)",
        _dark: "rgba(148, 163, 184, 0.20)",
      },
      "border.glass": {
        default: "rgba(255, 255, 255, 0.82)",
        _dark: "rgba(255, 255, 255, 0.12)",
      },
      "border.subtle": {
        default: "rgba(71, 85, 105, 0.14)",
        _dark: "rgba(226, 232, 240, 0.14)",
      },
      "glass.border": {
        default: "rgba(255, 255, 255, 0.82)",
        _dark: "rgba(255, 255, 255, 0.12)",
      },
      "text.primary": { default: "#182033", _dark: "#f7fafc" },
      "text.muted": { default: "#46556d", _dark: "#b0bbcd" },
      "fg.default": { default: "#182033", _dark: "#f7fafc" },
      "fg.muted": { default: "#46556d", _dark: "#b0bbcd" },
      "fg.subtle": { default: "#536176", _dark: "#a7b2c4" },
      "focus.ring": { default: "#2670e8", _dark: "#93c5fd" },
    },
  },
  styles: {
    global: {
      "html, body, #root": {
        minH: "100%",
        width: "100%",
      },
      html: {
        bg: "app.canvas",
      },
      body: {
        bg: "app.canvas",
        color: "text.primary",
      },
      "a, button, [role='button'], input, select, textarea": {
        _focusVisible: focusVisible,
      },
      "::selection": {
        bg: "primary.200",
        color: "gray.900",
      },
    },
  },
  layerStyles: {
    glass: {
      ...ambientReflection,
      bg: "surface.glass",
      borderWidth: "0",
      borderRadius: "glass",
      boxShadow: "glass.md",
      backdropFilter: "var(--marzban-glass-filter)",
      WebkitBackdropFilter: "var(--marzban-glass-filter)",
      _dark: {
        boxShadow: "glass.dark",
      },
    },
    "glass-strong": {
      ...ambientReflection,
      bg: "surface.glass-strong",
      borderWidth: "0",
      borderRadius: "glass",
      boxShadow: "glass.md",
      backdropFilter: "var(--marzban-glass-filter-strong)",
      WebkitBackdropFilter: "var(--marzban-glass-filter-strong)",
      _dark: {
        boxShadow: "glass.dark",
      },
    },
    panel: {
      bg: "surface.panel",
      borderWidth: "0",
      borderRadius: "panel",
      boxShadow: "panel",
      backgroundImage:
        "linear-gradient(135deg, rgba(255, 255, 255, 0.18), transparent 42%, rgba(96, 165, 250, 0.05))",
      _dark: {
        backgroundImage:
          "linear-gradient(135deg, rgba(255, 255, 255, 0.04), transparent 42%, rgba(96, 165, 250, 0.06))",
        boxShadow: "panel-dark",
      },
    },
    glassSubtle: {
      bg: "surface.inset",
      borderWidth: "0",
      boxShadow: "glass-subtle",
      _dark: {
        boxShadow: "glass-subtle-dark",
      },
    },
    glassHero: {
      ...ambientReflection,
      bg: "surface.glass-strong",
      backgroundImage:
        "linear-gradient(135deg, rgba(255, 255, 255, 0.40), rgba(91, 147, 247, 0.12))",
      borderWidth: "0",
      boxShadow: "glass.lg",
      backdropFilter: "var(--marzban-glass-filter-strong)",
      WebkitBackdropFilter: "var(--marzban-glass-filter-strong)",
      _dark: {
        backgroundImage:
          "linear-gradient(135deg, rgba(255, 255, 255, 0.07), rgba(37, 99, 235, 0.13))",
        boxShadow: "glass.dark",
      },
    },
    glassTopbar: {
      ...ambientReflection,
      bg: "surface.glass",
      borderWidth: "0",
      boxShadow:
        "inset 0 -1px 0 rgba(255, 255, 255, 0.38), 0 8px 24px rgba(15, 23, 42, 0.05)",
      backdropFilter: "var(--marzban-glass-filter)",
      WebkitBackdropFilter: "var(--marzban-glass-filter)",
      _dark: {
        boxShadow:
          "inset 0 -1px 0 rgba(255, 255, 255, 0.09), 0 8px 24px rgba(0, 0, 0, 0.20)",
      },
    },
  },
  components: {
    Card: {
      baseStyle: {
        container: {
          bg: "surface.panel",
          borderWidth: "0",
          borderRadius: "panel",
          boxShadow: "panel",
          backgroundImage:
            "linear-gradient(135deg, rgba(255, 255, 255, 0.16), transparent 44%, rgba(96, 165, 250, 0.05))",
          transition:
            "transform var(--marzban-motion-base) var(--marzban-ease-out), box-shadow var(--marzban-motion-base) var(--marzban-ease-out)",
          _dark: { boxShadow: "panel-dark" },
        },
      },
      variants: {
        glass: {
          container: {
            ...ambientReflection,
            bg: "surface.glass",
            borderWidth: "0",
            borderRadius: "glass",
            boxShadow: "glass.md",
            backdropFilter: "var(--marzban-glass-filter)",
            WebkitBackdropFilter: "var(--marzban-glass-filter)",
            _dark: { boxShadow: "glass.dark" },
          },
        },
      },
    },
    Button: {
      baseStyle: {
        borderRadius: "control",
        fontWeight: "semibold",
        transition:
          "transform var(--marzban-motion-fast) var(--marzban-ease-out), background-color var(--marzban-motion-fast) ease, box-shadow var(--marzban-motion-fast) ease",
        _focusVisible: {
          ...focusVisible,
        },
        _active: {
          transform: "scale(.975)",
        },
        _disabled: {
          transform: "none",
        },
      },
      variants: {
        glass: {
          bg: "surface.input",
          color: "fg.default",
          boxShadow: "glass-subtle",
          backdropFilter: "var(--marzban-glass-filter-subtle)",
          _hover: {
            bg: "surface.hover",
            boxShadow: "panel",
          },
          _dark: {
            boxShadow: "glass-subtle-dark",
          },
        },
      },
    },
    Menu: {
      baseStyle: {
        list: {
          ...ambientReflection,
          bg: "surface.glass-strong",
          borderWidth: "0",
          borderRadius: "panel",
          boxShadow: "glass.md",
          backdropFilter: "var(--marzban-glass-filter)",
          WebkitBackdropFilter: "var(--marzban-glass-filter)",
          p: "1.5",
          _dark: { boxShadow: "glass.dark" },
        },
        item: {
          borderRadius: "control",
          bg: "transparent",
          _focus: { bg: "surface.hover" },
          _hover: { bg: "surface.hover" },
        },
      },
    },
    Alert: {
      baseStyle: {
        container: {
          bg: "surface.inset",
          borderWidth: "0",
          borderRadius: "panel",
          boxShadow: "glass-subtle",
          fontSize: "sm",
          _dark: { boxShadow: "glass-subtle-dark" },
        },
      },
    },
    Select: {
      baseStyle: {
        field: {
          bg: "surface.input",
          borderColor: "border.subtle",
          borderRadius: "control",
          boxShadow: "inset 0 1px 0 rgba(255, 255, 255, .35)",
          _hover: { borderColor: "primary.300" },
          _focusVisible: focusVisible,
          _dark: { borderColor: "border.subtle" },
        },
      },
      variants: {
        outline: {
          field: {
            bg: "surface.input",
            borderColor: "border.subtle",
            _hover: { borderColor: "primary.300" },
            _focusVisible: focusVisible,
          },
        },
      },
    },
    FormHelperText: {
      baseStyle: {
        fontSize: "xs",
      },
    },
    FormLabel: {
      baseStyle: {
        fontSize: "sm",
        fontWeight: "semibold",
        mb: "1",
        _dark: { color: "gray.300" },
      },
    },
    Input: {
      baseStyle: {
        addon: {
          bg: "surface.inset",
          borderColor: "border.subtle",
          _dark: {
            borderColor: "border.subtle",
            _placeholder: {
              color: "gray.500",
            },
          },
        },
        field: {
          bg: "surface.input",
          borderColor: "border.subtle",
          borderRadius: "control",
          boxShadow: "inset 0 1px 0 rgba(255, 255, 255, .34)",
          _hover: {
            borderColor: "primary.300",
          },
          _focusVisible: {
            ...focusVisible,
            borderColor: "focus.ring",
          },
          _dark: {
            borderColor: "border.subtle",
            _disabled: {
              color: "gray.400",
              borderColor: "gray.500",
            },
            _placeholder: {
              color: "gray.500",
            },
          },
        },
      },
      variants: {
        outline: {
          field: {
            bg: "surface.input",
            borderColor: "border.subtle",
            _hover: { borderColor: "primary.300" },
            _focusVisible: {
              ...focusVisible,
              borderColor: "focus.ring",
            },
          },
          addon: {
            bg: "surface.inset",
            borderColor: "border.subtle",
          },
        },
      },
    },
    Textarea: {
      baseStyle: {
        bg: "surface.input",
        borderColor: "border.subtle",
        borderRadius: "control",
        boxShadow: "inset 0 1px 0 rgba(255, 255, 255, .34)",
        _hover: { borderColor: "primary.300" },
        _focusVisible: {
          ...focusVisible,
          borderColor: "focus.ring",
        },
        _dark: { borderColor: "border.subtle" },
      },
      variants: {
        outline: {
          bg: "surface.input",
          borderColor: "border.subtle",
          _hover: { borderColor: "primary.300" },
          _focusVisible: {
            ...focusVisible,
            borderColor: "focus.ring",
          },
        },
      },
    },
    Modal: {
      baseStyle: {
        overlay: {
          bg: "rgba(8, 15, 28, .32)",
          backdropFilter: "var(--marzban-overlay-filter)",
          WebkitBackdropFilter: "var(--marzban-overlay-filter)",
        },
        dialog: {
          ...ambientReflection,
          bg: "surface.glass-strong",
          borderWidth: "0",
          borderRadius: "glass",
          boxShadow: "glass.lg",
          backdropFilter: "var(--marzban-glass-filter-strong)",
          WebkitBackdropFilter: "var(--marzban-glass-filter-strong)",
          _dark: { boxShadow: "glass.dark" },
        },
        header: { borderBottomColor: "border.subtle" },
        footer: { borderTopColor: "border.subtle" },
      },
    },
    Drawer: {
      baseStyle: {
        overlay: {
          bg: "rgba(8, 15, 28, .28)",
          backdropFilter: "var(--marzban-overlay-filter)",
          WebkitBackdropFilter: "var(--marzban-overlay-filter)",
        },
        dialog: {
          ...ambientReflection,
          bg: "surface.glass-strong",
          borderWidth: "0",
          boxShadow: "glass.lg",
          backdropFilter: "var(--marzban-glass-filter-strong)",
          WebkitBackdropFilter: "var(--marzban-glass-filter-strong)",
          _dark: { boxShadow: "glass.dark" },
        },
      },
    },
    Popover: {
      baseStyle: {
        content: {
          ...ambientReflection,
          bg: "surface.glass-strong",
          borderWidth: "0",
          borderRadius: "panel",
          boxShadow: "glass.md",
          backdropFilter: "var(--marzban-glass-filter)",
          WebkitBackdropFilter: "var(--marzban-glass-filter)",
          _dark: { boxShadow: "glass.dark" },
          _focusVisible: focusVisible,
        },
        arrow: { bg: "surface.glass-strong" },
      },
    },
    Tooltip: {
      baseStyle: {
        bg: "surface.glass-strong",
        color: "fg.default",
        borderRadius: "control",
        boxShadow: "glass.md",
        backdropFilter: "var(--marzban-glass-filter-subtle)",
      },
    },
    Tabs: {
      baseStyle: {
        tablist: {
          w: "fit-content",
          maxW: "full",
          p: "1",
          gap: "1",
          borderBottom: "0",
          borderRadius: "panel",
          bg: "surface.inset",
          boxShadow: "glass-subtle",
          overflowX: "auto",
        },
        tab: {
          minH: "10",
          px: "4",
          borderRadius: "control",
          color: "fg.muted",
          fontWeight: "semibold",
          whiteSpace: "nowrap",
          _selected: {
            color: "primary.600",
            bg: "surface.glass-strong",
            boxShadow: "glass-subtle",
          },
          _focusVisible: focusVisible,
        },
        tabpanel: { px: "0" },
      },
    },
    Accordion: {
      baseStyle: {
        container: { borderColor: "border.subtle" },
        button: {
          borderRadius: "control",
          _hover: { bg: "surface.hover" },
          _focusVisible: focusVisible,
        },
        panel: { color: "fg.muted" },
      },
    },
    Checkbox: {
      baseStyle: {
        control: {
          bg: "surface.input",
          borderColor: "border.subtle",
          borderRadius: "6px",
          _focusVisible: focusVisible,
        },
      },
    },
    Switch: {
      baseStyle: {
        track: {
          bg: "surface.track",
          boxShadow: "inset 0 1px 2px rgba(15, 23, 42, .12)",
        },
      },
    },
    Progress: {
      baseStyle: {
        track: {
          bg: "surface.track",
          borderRadius: "full",
          overflow: "hidden",
        },
      },
    },
    Table: {
      baseStyle: {
        table: {
          borderCollapse: "separate",
          borderSpacing: 0,
        },
        thead: {
          borderBottomColor: "border.subtle",
        },
        th: {
          background: "surface.inset",
          borderColor: "border.subtle !important",
          borderBottomColor: "border.subtle !important",
          borderTop: "0",
          _dark: {
            borderColor: "border.subtle !important",
            background: "surface.inset",
          },
        },
        td: {
          transition: "background-color .16s ease-out",
          borderColor: "border.subtle",
          borderBottomColor: "border.subtle !important",
          _dark: {
            borderColor: "border.subtle",
            borderBottomColor: "border.subtle !important",
          },
        },
        tr: {
          "&.interactive": {
            cursor: "pointer",
            _hover: {
              "& > td": {
                bg: "surface.hover",
              },
              _dark: {
                "& > td": {
                  bg: "surface.hover",
                },
              },
            },
          },
          _last: {
            "& > td": {
              _first: {
                borderBottomLeftRadius: "8px",
              },
              _last: {
                borderBottomRightRadius: "8px",
              },
            },
          },
        },
      },
    },
  },
});
