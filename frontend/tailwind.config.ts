import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#18181b",
        clinical: {
          50: "#f3f1ff",
          100: "#e5e0ff",
          500: "#7765e9",
          600: "#6553d8",
          700: "#5140bb"
        }
      },
      boxShadow: {
        soft: "0 12px 35px rgba(24, 24, 27, 0.07)"
      }
    }
  },
  plugins: []
};

export default config;
