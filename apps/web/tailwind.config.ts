import type { Config } from "tailwindcss";

/**
 * Semt Pazarı token set — grounded in the actual subject (produce crates,
 * chalk price boards, official hal bulletins) rather than a generic SaaS
 * palette. Kraft-paper surfaces, crate-red as the primary accent, leaf-green
 * and price-tag ochre as secondaries. Flat panels + thin rules instead of
 * soft drop shadows; radii stay small (this is a price ledger, not a card kit).
 */
const config: Config = {
  content: ["./src/app/**/*.{ts,tsx}", "./src/components/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      fontFamily: {
        sans: ["var(--font-body)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "system-ui", "sans-serif"],
      },
      colors: {
        // Primary accent: crate-stamp red.
        crate: {
          50: "#FBEEEA",
          100: "#F4D6CC",
          200: "#E7AC99",
          300: "#D98567",
          400: "#CE633F",
          500: "#C4432B", // primary
          600: "#A6371F",
          700: "#872C19",
          800: "#682113",
          900: "#4A170D",
        },
        // Secondary accent: produce-leaf green (market-day chips, positive stats).
        leaf: {
          50: "#F2F4EA",
          100: "#E1E7CD",
          200: "#C4CF9E",
          300: "#A7B770",
          400: "#8FA355",
          500: "#7A8C4A", // secondary
          600: "#63723B",
          700: "#4D592D",
          800: "#37401F",
          900: "#212713",
        },
        // Tertiary accent: price-tag ochre (deltas, highlights).
        ochre: {
          50: "#FDF6E7",
          100: "#F9E7BC",
          300: "#EFC474",
          500: "#E0A93C",
          700: "#B3822A",
        },
        // Surfaces: kraft paper, not cold off-white.
        surface: {
          DEFAULT: "#FFFFFF",
          subtle: "#F7F3EA",
          muted: "#EFE8D8",
          border: "#DCD3BE",
        },
        ink: {
          DEFAULT: "#1F2A1C",
          soft: "#3F4A39",
          muted: "#6B7263",
          faint: "#8C9284",
        },
        success: "#5C7A2E",
        danger: "#A6371F",
      },
      boxShadow: {
        // Flat by design: a single hairline, no blurred glow. Kept as a
        // token (rather than inlined `border`) so a future surface that
        // truly needs lift (a modal, a dropdown) has one place to define it.
        soft: "0 1px 0 0 rgba(31, 42, 28, 0.08)",
        ring: "0 0 0 3px rgba(196, 67, 43, 0.22)",
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #C4432B 0%, #E0A93C 100%)",
      },
      borderRadius: {
        xl: "6px",
        "2xl": "8px",
      },
    },
  },
  plugins: [],
};

export default config;
