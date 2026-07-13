import { fetch } from "service/http";
import {
  SubscriptionSecuritySettings,
  SubscriptionSecuritySettingsUpdate,
} from "types/Mgma";
import { create } from "zustand";

type SubscriptionSecurityState = {
  isOpen: boolean;
  isLoading: boolean;
  isSaving: boolean;
  settings: SubscriptionSecuritySettings | null;
  open: () => void;
  close: () => void;
  load: () => Promise<void>;
  save: (
    settings: SubscriptionSecuritySettingsUpdate
  ) => Promise<SubscriptionSecuritySettings>;
};

export const useSubscriptionSecurity = create<SubscriptionSecurityState>(
  (set) => ({
    isOpen: false,
    isLoading: false,
    isSaving: false,
    settings: null,
    open: () => set({ isOpen: true }),
    close: () => set({ isOpen: false }),
    load: async () => {
      set({ isLoading: true });
      try {
        const settings = await fetch<SubscriptionSecuritySettings>(
          "/subscription/settings",
          {
            headers: { "Cache-Control": "no-store" },
          }
        );
        set({ settings });
      } finally {
        set({ isLoading: false });
      }
    },
    save: async (body) => {
      set({ isSaving: true });
      try {
        const settings = await fetch<SubscriptionSecuritySettings>(
          "/subscription/settings",
          {
            method: "PUT",
            body,
            headers: { "Cache-Control": "no-store" },
          }
        );
        set({ settings });
        return settings;
      } finally {
        set({ isSaving: false });
      }
    },
  })
);
