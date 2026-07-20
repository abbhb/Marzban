import { fetch } from "service/http";
import { MgmaGrant } from "types/Mgma";
import { User } from "types/User";
import { create } from "zustand";
import { useDashboard } from "./DashboardContext";

type MgmaState = {
  user: User | null;
  grant: MgmaGrant | null;
  isOpen: boolean;
  isLoading: boolean;
  isRevoking: boolean;
  isRegeneratingSubscription: boolean;
  isExpired: boolean;
  error: string | null;
  open: (user: User) => Promise<void>;
  regenerate: () => Promise<void>;
  regenerateSubscription: () => Promise<void>;
  revoke: () => Promise<void>;
  expire: (expectedUrl: string) => void;
  close: () => void;
};

let requestSequence = 0;

const requestGrant = async (user: User): Promise<MgmaGrant> => {
  const clientRequestedAt = performance.now();
  const grant = await fetch<MgmaGrant>(
    `/user/${encodeURIComponent(user.username)}/mgma`,
    {
      method: "POST",
      headers: {
        "Cache-Control": "no-store",
      },
    }
  );
  return { ...grant, client_requested_at_ms: clientRequestedAt };
};

const issueGrant = async (user: User): Promise<void> => {
  const sequence = ++requestSequence;
  useMgma.setState({
    user,
    grant: null,
    isOpen: true,
    isLoading: true,
    isRevoking: false,
    isRegeneratingSubscription: false,
    isExpired: false,
    error: null,
  });

  try {
    const grant = await requestGrant(user);
    if (sequence !== requestSequence) return;
    useMgma.setState({
      grant,
      isLoading: false,
    });
  } catch (error) {
    if (sequence !== requestSequence) return;
    useMgma.setState({
      grant: null,
      isLoading: false,
      error: "mgma.issueError",
    });
  }
};

export const useMgma = create<MgmaState>((set, get) => ({
  user: null,
  grant: null,
  isOpen: false,
  isLoading: false,
  isRevoking: false,
  isRegeneratingSubscription: false,
  isExpired: false,
  error: null,
  open: async (user) => {
    ++requestSequence;
    set({
      user,
      grant: null,
      isOpen: true,
      isLoading: false,
      isRevoking: false,
      isRegeneratingSubscription: false,
      isExpired: false,
      error: null,
    });
  },
  regenerate: async () => {
    const user = get().user;
    if (user) await issueGrant(user);
  },
  regenerateSubscription: async () => {
    const user = get().user;
    if (!user) return;
    const sequence = ++requestSequence;
    set({
      grant: null,
      isLoading: true,
      isRevoking: false,
      isRegeneratingSubscription: true,
      isExpired: false,
      error: null,
    });
    try {
      const clientRequestedAt = performance.now();
      const grant = await fetch<MgmaGrant>(
        `/user/${encodeURIComponent(user.username)}/subscription/regenerate`,
        {
          method: "POST",
          headers: {
            "Cache-Control": "no-store",
          },
        }
      );
      if (sequence !== requestSequence) return;
      useDashboard.getState().refetchUsers();
      set({
        grant: { ...grant, client_requested_at_ms: clientRequestedAt },
        isLoading: false,
        isRegeneratingSubscription: false,
      });
    } catch (error) {
      if (sequence === requestSequence) {
        set({
          grant: null,
          isLoading: false,
          isRegeneratingSubscription: false,
          error: "mgma.subscriptionRegenerateError",
        });
      }
      throw error;
    }
  },
  revoke: async () => {
    const user = get().user;
    if (!user) return;
    const sequence = ++requestSequence;
    set({ isRevoking: true, error: null });
    try {
      await fetch(`/user/${encodeURIComponent(user.username)}/mgma`, {
        method: "DELETE",
        headers: {
          "Cache-Control": "no-store",
        },
      });
      if (sequence !== requestSequence) return;
      set({ grant: null, isRevoking: false, isExpired: false });
    } catch (error) {
      if (sequence === requestSequence)
        set({ isRevoking: false, error: "mgma.revokeError" });
      throw error;
    }
  },
  expire: (expectedUrl) => {
    if (get().grant?.url !== expectedUrl) return;
    set({
      grant: null,
      isLoading: false,
      isExpired: true,
    });
  },
  close: () => {
    ++requestSequence;
    set({
      user: null,
      grant: null,
      isOpen: false,
      isLoading: false,
      isRevoking: false,
      isRegeneratingSubscription: false,
      isExpired: false,
      error: null,
    });
  },
}));
