import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        paper: "var(--paper)",
        ink: "var(--ink)",
        signal: "var(--signal)",
        mint: "var(--mint)",
        coral: "var(--coral)",
        gold: "var(--gold)"
      },
      boxShadow: {
        lift: "0 18px 46px rgba(22, 39, 58, 0.12)"
      },
      borderRadius: {
        shell: "8px"
      }
    }
  },
  plugins: []
};

export default config;
