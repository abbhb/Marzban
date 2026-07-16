import { ChakraProvider, localStorageManager } from "@chakra-ui/react";
import dayjs from "dayjs";
import Duration from "dayjs/plugin/duration";
import LocalizedFormat from "dayjs/plugin/localizedFormat";
import RelativeTime from "dayjs/plugin/relativeTime";
import Timezone from "dayjs/plugin/timezone";
import utc from "dayjs/plugin/utc";
import { i18nReady } from "locales/i18n";
import { LiquidGlassEnvironment } from "components/LiquidGlassEnvironment";
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "react-query";
import { queryClient } from "utils/react-query";
import { updateThemeColor } from "utils/themeColor";
import { theme } from "../chakra.config";
import App from "./App";
import { bootStage, failBoot } from "./boot";
import { preloadInitialRoute } from "./pages/Router";
import "index.scss";

dayjs.extend(Timezone);
dayjs.extend(LocalizedFormat);
dayjs.extend(utc);
dayjs.extend(RelativeTime);
dayjs.extend(Duration);

updateThemeColor(localStorageManager.get() || "light");

const settleWithin = async <T,>(promise: Promise<T>, timeoutMs: number) => {
  let timeout: number | undefined;
  const timeoutPromise = new Promise<never>((_, reject) => {
    timeout = window.setTimeout(
      () => reject(new Error(`Dashboard startup timed out after ${timeoutMs}ms`)),
      timeoutMs
    );
  });
  try {
    return await Promise.race([promise, timeoutPromise]);
  } finally {
    if (timeout !== undefined) window.clearTimeout(timeout);
  }
};

const renderDashboard = async () => {
  bootStage("runtime");
  // Start the route chunk while the locale catalog is in flight. The router
  // will reuse the same module request and can start its data loader sooner.
  void preloadInitialRoute().catch(() => undefined);

  try {
    await settleWithin(i18nReady, 15000);
  } catch (error) {
    // i18next can still render its fallback strings after a catalog error.
    console.error("Failed to initialize dashboard translations", error);
  }

  bootStage("locale");
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <ChakraProvider theme={theme}>
        <QueryClientProvider client={queryClient}>
          <LiquidGlassEnvironment>
            <App />
          </LiquidGlassEnvironment>
        </QueryClientProvider>
      </ChakraProvider>
    </React.StrictMode>
  );
};

renderDashboard().catch((error) => {
  console.error("Failed to start dashboard", error);
  failBoot();
});
