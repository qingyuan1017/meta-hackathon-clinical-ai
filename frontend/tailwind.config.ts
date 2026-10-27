import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#10233d",
        clinical: {
          50: "#eefbf9",
          100: "#d5f5ef",
          500: "#11a98f",
          600: "#078a76",
          700: "#096f61"
        }
      },
      boxShadow: {
        soft: "0 18px 50px rgba(16, 35, 61, 0.08)"
      }
    }
  },
  plugins: []
};

export default config;
