import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17201f",
        clinical: {
          50: "#eef5f2",
          100: "#d8e9e3",
          500: "#2f7c72",
          600: "#1f6b62",
          700: "#174f49"
        }
      },
      boxShadow: {
        soft: "0 1px 2px rgba(23, 32, 31, 0.04), 0 8px 24px rgba(23, 32, 31, 0.055)"
      }
    }
  },
  plugins: []
};

export default config;
