import reactRefresh from "@vitejs/plugin-react-refresh";
import { resolve } from "path";
import { defineConfig, loadEnv, searchForWorkspaceRoot } from "vite";
import restart from "vite-plugin-restart";
import UnoCSS from "unocss/vite";
import { sentryVitePlugin } from "@sentry/vite-plugin";

// https://vitejs.dev/config/
export default defineConfig(({ command, mode }) => {
  // Load env file based on `mode` in the current working directory
  const env = loadEnv(mode, process.cwd(), '');

  return {
    optimizeDeps: {
      exclude: ["@empirica/tajriba", "@empirica/core"],
    },
    server: {
      port: 8844,
      open: false,
      strictPort: true,
      host: "0.0.0.0",
      fs: {
        allow: [
          // search up for workspace root
          searchForWorkspaceRoot(process.cwd()),
        ],
      },
    },
    build: {
      minify: false,
      sourcemap: true  // Required for Sentry
    },
    clearScreen: false,
    plugins: [
      restart({
        restart: [
          "./uno.config.cjs",
          "./node_modules/@empirica/core/dist/**/*.{js,ts,jsx,tsx,css}",
          "./node_modules/@empirica/core/assets/**/*.css",
        ],
      }),
      UnoCSS(),
      reactRefresh(),
      // Add Sentry plugin last
      sentryVitePlugin({
        org: env.SENTRY_ORG,
        project: env.SENTRY_PROJECT,
        authToken: env.SENTRY_AUTH_TOKEN,
      }),
    ],
    define: {
      "process.env": {
        NODE_ENV: process.env.NODE_ENV || "development",
      },
    },
  };
});