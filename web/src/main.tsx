import "./styles/globals.css";

import { createRoot } from "react-dom/client";

import App from "./App";
import { ToastProvider } from "./components/toasts";
import { ThemeProvider } from "./lib/theme";

// No <StrictMode>: its double-run of effects in development would call
// createMediaElementSource twice on the same <video>, which throws.
createRoot(document.getElementById("root")!).render(
  <ThemeProvider>
    <ToastProvider>
      <App />
    </ToastProvider>
  </ThemeProvider>,
);
