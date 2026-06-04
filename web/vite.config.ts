import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { traeBadgePlugin } from "vite-plugin-trae-solo-badge";

// https://vite.dev/config/
export default defineConfig({
  base: "/console/",
  build: {
    sourcemap: "hidden",
    outDir: "dist",
  },
  server: {
    port: 4173,
    proxy: {
      "/health": "http://127.0.0.1:8000",
      "/nl2sql": "http://127.0.0.1:8000",
      "/chat": "http://127.0.0.1:8000",
      "/admin": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
      "/relation-graph": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
  plugins: [
    react({
      babel: {
        plugins: [
          "react-dev-locator",
        ],
      },
    }),
    traeBadgePlugin({
      variant: "dark",
      position: "bottom-right",
      prodOnly: true,
      clickable: true,
      clickUrl: "https://www.trae.ai/solo?showJoin=1",
      autoTheme: true,
      autoThemeTarget: "#root",
    }),
    tsconfigPaths(),
  ],
});
