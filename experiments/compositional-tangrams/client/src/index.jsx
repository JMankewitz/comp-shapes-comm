import React from "react";
import { createRoot } from "react-dom/client";
import "@unocss/reset/tailwind-compat.css";
import "virtual:uno.css";
import "../node_modules/@empirica/core/dist/player.css";
import App from "./App";
import "./index.css";

import * as Sentry from "@sentry/react";

Sentry.init({
    replaysSessionSampleRate: 1.0,
    replaysOnErrorSampleRate: 1.0,
    dsn: "https://39dffa4a7bdcafb5290401881940b4fa@o4506525893853184.ingest.us.sentry.io/4508609472954368",
    integrations: [
	Sentry.browserTracingIntegration(),
        Sentry.replayIntegration({
	    maskAllText: false,
	    blockAllMedia: false,
        maskAllInputs: false,
        networkDetailHasUrls: true,
	}),
    ],
    release: "comp-shapes-comm@0.0.3",
});


const container = document.getElementById("root");
const root = createRoot(container); // createRoot(container!) if you use TypeScript
root.render(
  <React.StrictMode>
      <App />
  </React.StrictMode>
);
