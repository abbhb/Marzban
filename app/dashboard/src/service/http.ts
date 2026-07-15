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
      if (!window.location.hash.startsWith("#/portal/login")) {
        window.location.hash = "/portal/login";
      }
    }
    throw error;
  });
};
