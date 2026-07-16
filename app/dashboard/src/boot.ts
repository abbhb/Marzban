export type BootStage = "styles" | "runtime" | "locale" | "route";

type BootController = {
  progress: (percent: number, label?: string) => void;
  stage: (stage: BootStage) => void;
  fail: (message?: string) => void;
  complete: () => void;
};

export const CHUNK_RELOAD_KEY = "marzban-chunk-reload";

declare global {
  interface Window {
    __MARZBAN_BOOT__?: BootController;
  }
}

export const bootStage = (stage: BootStage) => {
  window.__MARZBAN_BOOT__?.stage(stage);
};

export const completeBoot = () => {
  try {
    sessionStorage.removeItem(CHUNK_RELOAD_KEY);
  } catch (error) {
    // Storage can be unavailable in privacy-restricted browser contexts.
  }
  window.__MARZBAN_BOOT__?.complete();
};

export const failBoot = (message?: string) => {
  window.__MARZBAN_BOOT__?.fail(message);
};
