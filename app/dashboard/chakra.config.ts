import { extendTheme } from "@chakra-ui/react";
export const theme = extendTheme({
  shadows: {
    outline: "0 0 0 3px rgba(38, 112, 232, 0.28)",
    glass: {
      md: "inset 0 1px 0 rgba(255, 255, 255, 0.72), inset 0 -1px 0 rgba(255, 255, 255, 0.12), 0 0 0 1px rgba(255, 255, 255, 0.40), 0 18px 48px rgba(31, 60, 105, 0.12)",
      lg: "inset 0 1px 0 rgba(255, 255, 255, 0.78), inset 0 -1px 0 rgba(255, 255, 255, 0.14), 0 0 0 1px rgba(255, 255, 255, 0.46), 0 24px 68px rgba(31, 60, 105, 0.16)",
      hover: "inset 0 1px 0 rgba(255, 255, 255, 0.84), inset 0 -1px 0 rgba(255, 255, 255, 0.16), 0 0 0 1px rgba(255, 255, 255, 0.54), 0 28px 76px rgba(31, 60, 105, 0.20)",
      dark: "inset 0 1px 0 rgba(255, 255, 255, 0.16), inset 0 -1px 0 rgba(255, 255, 255, 0.04), 0 0 0 1px rgba(255, 255, 255, 0.11), 0 20px 56px rgba(0, 0, 0, 0.32)",
      "dark-hover": "inset 0 1px 0 rgba(255, 255, 255, 0.20), inset 0 -1px 0 rgba(255, 255, 255, 0.05), 0 0 0 1px rgba(255, 255, 255, 0.15), 0 28px 72px rgba(0, 0, 0, 0.40)",
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
    "light-border": "#d2d2d4",
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
      750: "#222C3B",
    },
  },
  semanticTokens: {
    colors: {
      "app.canvas": { default: "#eef3fa", _dark: "#090e17" },
      "surface.glass": {
        default: "rgba(255, 255, 255, 0.50)",
        _dark: "rgba(13, 20, 33, 0.56)",
      },
      "surface.glass-strong": {
        default: "rgba(255, 255, 255, 0.68)",
        _dark: "rgba(13, 20, 33, 0.72)",
      },
      "surface.panel": {
        default: "rgba(255, 255, 255, 0.70)",
        _dark: "rgba(18, 27, 43, 0.74)",
      },
      "surface.muted": {
        default: "rgba(241, 245, 249, 0.48)",
        _dark: "rgba(30, 41, 59, 0.48)",
      },
      "surface.input": {
        default: "rgba(255, 255, 255, 0.62)",
        _dark: "rgba(15, 23, 42, 0.62)",
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
      "text.muted": { default: "#5f6c82", _dark: "#a7b2c4" },
      "fg.default": { default: "#182033", _dark: "#f7fafc" },
      "fg.muted": { default: "#5f6c82", _dark: "#a7b2c4" },
      "fg.subtle": { default: "#6b778c", _dark: "#94a3b8" },
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
        backgroundImage:
          "radial-gradient(circle at 12% 8%, rgba(74, 139, 255, 0.18), transparent 31rem), radial-gradient(circle at 88% 12%, rgba(45, 212, 191, 0.12), transparent 29rem)",
        backgroundAttachment: { base: "scroll", md: "fixed" },
        _dark: {
          backgroundImage:
            "radial-gradient(circle at 12% 8%, rgba(59, 130, 246, 0.16), transparent 31rem), radial-gradient(circle at 88% 12%, rgba(20, 184, 166, 0.10), transparent 29rem)",
        },
      },
      "::selection": {
        bg: "primary.200",
        color: "gray.900",
      },
    },
  },
  layerStyles: {
    glass: {
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
      _dark: {
        boxShadow: "panel-dark",
      },
    },
    glassSubtle: {
      bg: "surface.muted",
      borderWidth: "0",
      boxShadow: "glass-subtle",
      backdropFilter: "var(--marzban-glass-filter-subtle)",
      WebkitBackdropFilter: "var(--marzban-glass-filter-subtle)",
      _dark: {
        boxShadow: "glass-subtle-dark",
      },
    },
    glassHero: {
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
          _dark: { boxShadow: "panel-dark" },
        },
      },
      variants: {
        glass: {
          container: {
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
        _focusVisible: {
          boxShadow: "outline",
        },
      },
    },
    Menu: {
      baseStyle: {
        list: {
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
        },
      },
    },
    Alert: {
      baseStyle: {
        container: {
          borderRadius: "6px",
          fontSize: "sm",
        },
      },
    },
    Select: {
      baseStyle: {
        field: {
          _dark: {
            borderColor: "gray.600",
            borderRadius: "6px",
          },
          _light: {
            borderRadius: "6px",
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
        fontWeight: "medium",
        mb: "1",
        _dark: { color: "gray.300" },
      },
    },
    Input: {
      baseStyle: {
        addon: {
          _dark: {
            borderColor: "gray.600",
            _placeholder: {
              color: "gray.500",
            },
          },
        },
        field: {
          _focusVisible: {
            boxShadow: "none",
            borderColor: "primary.200",
            outlineColor: "primary.200",
          },
          _dark: {
            borderColor: "gray.600",
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
          background: "surface.glass-strong",
          borderColor: "border.subtle !important",
          borderBottomColor: "border.subtle !important",
          borderTop: "0",
          backdropFilter: "var(--marzban-glass-filter-subtle)",
          WebkitBackdropFilter: "var(--marzban-glass-filter-subtle)",
          _dark: {
            borderColor: "border.subtle !important",
            background: "surface.glass-strong",
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
