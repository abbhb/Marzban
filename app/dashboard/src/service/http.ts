import { FetchOptions, $fetch as ohMyFetch } from "ofetch";
import { getAuthToken } from "utils/authStorage";
import {
  getPortalAuthToken,
  removePortalAuthToken,
} from "utils/portalAuthStorage";

export const $fetch = ohMyFetch.create({
  // Keep production API routing safe even when a manual/offline build omits
  // VITE_BASE_API. The documented build script still sets the same value.
  baseURL: import.meta.env.VITE_BASE_API || "/api/",
});

export const fetcher = <T = any>(
  url: string,
  ops: FetchOptions<"json"> = {}
) => {
  const token = getAuthToken();
  if (token) {
    ops["headers"] = {
      ...(ops?.headers || {}),
      Authorization: `Bearer ${getAuthToken()}`,
    };
  }
  return $fetch<T>(url, ops);
};

export const fetch = fetcher;

export const portalFetch = <T = any>(
  url: string,
  ops: FetchOptions<"json"> = {}
) => {
  const token = getPortalAuthToken();
  if (token) {
    ops["headers"] = {
      ...(ops?.headers || {}),
      Authorization: `Bearer ${token}`,
    };
  }
  return $fetch<T>(url, ops).catch((error: any) => {
    const status = error?.statusCode || error?.response?.status;
    if (token && status === 401) {
      removePortalAuthToken();
      if (!/^#\/login\/?(?:\?|$)/.test(window.location.hash)) {
        window.location.hash = "/login";
      }
    }
    throw error;
  });
};

// Normalize FastAPI text, field maps, and validation arrays before rendering.
export const errorMessage = (error: any, fallback: string): string => {
  const detail = error?.data?.detail ?? error?.response?._data?.detail;
  const describe = (value: unknown): string => {
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return value.map(describe).filter(Boolean).join("; ");
    if (value && typeof value === "object") {
      const record = value as Record<string, unknown>;
      if (typeof record.msg === "string") {
        return `${Array.isArray(record.loc) ? record.loc.join(".") + ": " : ""}${record.msg}`;
      }
      return Object.entries(record).map(([field, message]) => `${field}: ${describe(message)}`).join("; ");
    }
    return "";
  };
  return describe(detail) || fallback;
};
