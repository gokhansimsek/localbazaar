import type { Config } from "tailwindcss";

/**
 * Stripe-inspired palette. Brand indigo (#635BFF), off-white surfaces (#F6F9FC),
 * gradient accents toward sky / pink for hover and highlight states.
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
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        display: ["var(--font-inter)", "system-ui", "sans-serif"],
      },
      colors: {
        // Brand
        indigo: {
          50: "#F5F5FF",
          100: "#EDEBFF",
          200: "#D9D6FF",
          300: "#BAB4FF",
          400: "#928BFF",
          500: "#635BFF", // primary
          600: "#5048E5",
          700: "#3D36C7",
          800: "#2D27A0",
          900: "#1F1A78",
        },
        // Surfaces (Stripe-ish soft whites + slate)
        surface: {
          DEFAULT: "#FFFFFF",
          subtle: "#F6F9FC",
          muted: "#EFF3F8",
          border: "#E3E8EF",
        },
        ink: {
          DEFAULT: "#0A2540", // Stripe deep navy
          soft: "#425466",
          muted: "#697386",
          faint: "#8792A2",
        },
        accent: {
          sky: "#00D4FF",
          pink: "#FF7AB6",
          violet: "#A78BFA",
        },
        success: "#0FB67A",
        danger: "#E5484D",
      },
      boxShadow: {
        soft: "0 4px 24px -8px rgba(50, 50, 93, 0.12), 0 2px 6px -2px rgba(0, 0, 0, 0.04)",
        ring: "0 0 0 4px rgba(99, 91, 255, 0.18)",
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #635BFF 0%, #A78BFA 45%, #00D4FF 100%)",
        "page-glow":
          "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(99,91,255,0.18), transparent)",
      },
      borderRadius: {
        xl: "12px",
        "2xl": "16px",
      },
    },
  },
  plugins: [],
};

export default config;
