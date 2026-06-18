/** @type {import('tailwindcss').Config} */

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    container: {
      center: true,
    },
    extend: {
      colors: {
        accent: {
          DEFAULT: "#00c2ff",
          50: "#e5faff",
          100: "#b8f0ff",
          200: "#85e5ff",
          300: "#52d9ff",
          400: "#1fceff",
          500: "#00c2ff",
          600: "#009fd4",
          700: "#007da8",
          800: "#005c7d",
          900: "#003d54",
        },
        surface: {
          base: "#080c0f",
          raised: "#0f1419",
          overlay: "#151b22",
        },
        border: {
          subtle: "rgba(255,255,255,0.06)",
          muted: "rgba(255,255,255,0.10)",
          accent: "rgba(0,194,255,0.18)",
        },
        text: {
          primary: "#e8edf2",
          secondary: "#8a9baa",
          tertiary: "#556677",
        },
      },
      fontFamily: {
        sans: ['"DM Sans"', "system-ui", "-apple-system", "sans-serif"],
        mono: ['"JetBrains Mono"', "monospace"],
        display: ['"Rajdhani"', "sans-serif"],
      },
      borderRadius: {
        sm: "4px",
        md: "6px",
        lg: "10px",
        xl: "14px",
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }],
      },
    },
  },
  plugins: [],
};
