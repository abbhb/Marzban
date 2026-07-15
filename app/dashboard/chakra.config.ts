import { extendTheme } from "@chakra-ui/react";
export const theme = extendTheme({
  shadows: {
    outline: "0 0 0 3px rgba(38, 112, 232, 0.28)",
    glass: {
      md: "0 1px 2px rgba(15, 23, 42, 0.06), 0 18px 48px rgba(15, 23, 42, 0.10)",
      lg: "0 2px 4px rgba(15, 23, 42, 0.08), 0 24px 64px rgba(15, 23, 42, 0.14)",
      dark: "0 1px 2px rgba(0, 0, 0, 0.24), 0 20px 56px rgba(0, 0, 0, 0.30)",
    },
    panel:
      "0 1px 2px rgba(15, 23, 42, 0.05), 0 10px 30px rgba(15, 23, 42, 0.07)",
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
        default: "rgba(255, 255, 255, 0.72)",
        _dark: "rgba(17, 24, 39, 0.72)",
      },
      "surface.glass-strong": {
        default: "rgba(255, 255, 255, 0.88)",
        _dark: "rgba(17, 24, 39, 0.88)",
      },
      "surface.panel": {
        default: "rgba(255, 255, 255, 0.92)",
        _dark: "rgba(22, 30, 46, 0.92)",
      },
      "surface.muted": {
        default: "rgba(241, 245, 249, 0.82)",
        _dark: "rgba(30, 41, 59, 0.78)",
      },
      "surface.input": {
        default: "rgba(255, 255, 255, 0.88)",
        _dark: "rgba(15, 23, 42, 0.88)",
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
      border: "1px solid",
      borderColor: "border.glass",
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
      border: "1px solid",
      borderColor: "border.glass",
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
      border: "1px solid",
      borderColor: "border.subtle",
      borderRadius: "panel",
      boxShadow: "panel",
    },
    glassSubtle: {
      bg: "surface.muted",
      border: "1px solid",
      borderColor: "border.subtle",
      backdropFilter: "var(--marzban-glass-filter-subtle)",
      WebkitBackdropFilter: "var(--marzban-glass-filter-subtle)",
    },
    glassHero: {
      bg: "surface.glass-strong",
      backgroundImage:
        "linear-gradient(135deg, rgba(255, 255, 255, 0.40), rgba(91, 147, 247, 0.12))",
      border: "1px solid",
      borderColor: "border.glass",
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
      borderBottom: "1px solid",
      borderColor: "border.glass",
      boxShadow: "0 8px 24px rgba(15, 23, 42, 0.05)",
      backdropFilter: "var(--marzban-glass-filter)",
      WebkitBackdropFilter: "var(--marzban-glass-filter)",
    },
  },
  components: {
    Card: {
      baseStyle: {
        container: {
          bg: "surface.panel",
          border: "1px solid",
          borderColor: "border.subtle",
          borderRadius: "panel",
          boxShadow: "panel",
        },
      },
      variants: {
        glass: {
          container: {
            bg: "surface.glass",
            borderColor: "border.glass",
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
          borderColor: "border.glass",
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
          borderBottomColor: "light-border",
        },
        th: {
          background: "#F9FAFB",
          borderColor: "light-border !important",
          borderBottomColor: "light-border !important",
          borderTop: "1px solid ",
          borderTopColor: "light-border !important",
          _first: {
            borderLeft: "1px solid",
            borderColor: "light-border !important",
          },
          _last: {
            borderRight: "1px solid",
            borderColor: "light-border !important",
          },
          _dark: {
            borderColor: "gray.600 !important",
            background: "gray.750",
          },
        },
        td: {
          transition: "all .1s ease-out",
          borderColor: "light-border",
          borderBottomColor: "light-border !important",
          _first: {
            borderLeft: "1px solid",
            borderColor: "light-border",
            _dark: {
              borderColor: "gray.600",
            },
          },
          _last: {
            borderRight: "1px solid",
            borderColor: "light-border",
            _dark: {
              borderColor: "gray.600",
            },
          },
          _dark: {
            borderColor: "gray.600",
            borderBottomColor: "gray.600 !important",
          },
        },
        tr: {
          "&.interactive": {
            cursor: "pointer",
            _hover: {
              "& > td": {
                bg: "gray.200",
              },
              _dark: {
                "& > td": {
                  bg: "gray.750",
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
