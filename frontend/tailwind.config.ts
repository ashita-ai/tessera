import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: "var(--bg)", raised: "var(--bg-raised)", surface: "var(--bg-surface)", hover: "var(--bg-hover)" },
        accent: { DEFAULT: "var(--accent)", dim: "var(--accent-dim)", mid: "var(--accent-mid)" },
        red: { DEFAULT: "var(--red)", dim: "var(--red-dim)" },
        amber: { DEFAULT: "var(--amber)", dim: "var(--amber-dim)" },
        green: "var(--green)",
        t1: "var(--text-1)",
        t2: "var(--text-2)",
        t3: "var(--text-3)",
        line: { DEFAULT: "var(--line)", strong: "var(--line-strong)" },
      },
      fontFamily: {
        sans: ["DM Sans", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.65rem", { lineHeight: "1rem" }],
      },
    },
  },
  plugins: [],
} satisfies Config;
