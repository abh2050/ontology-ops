import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { initializeAuth } from "./auth";
import "./styles.css";
import "./workspace.css";

const client = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, retry: false } },
});
const root = ReactDOM.createRoot(document.getElementById("root")!);
async function start() {
  let authError = "";
  if (
    !import.meta.env.VITE_APP_MODE ||
    import.meta.env.VITE_APP_MODE === "live"
  ) {
    try {
      await initializeAuth();
    } catch (e) {
      authError = (e as Error).message;
    }
  }
  root.render(
    <React.StrictMode>
      <QueryClientProvider client={client}>
        <App initialAuthError={authError} />
      </QueryClientProvider>
    </React.StrictMode>,
  );
}
void start();
