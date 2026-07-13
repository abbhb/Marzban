import { FetchOptions, $fetch as ohMyFetch } from "ofetch";
import { getAuthToken } from "utils/authStorage";
import { getPortalAuthToken } from "utils/portalAuthStorage";

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
  return $fetch<T>(url, ops);
};
