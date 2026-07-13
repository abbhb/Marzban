const PORTAL_TOKEN_KEY = "marzban-portal-token";

export const getPortalAuthToken = (): string | null =>
  localStorage.getItem(PORTAL_TOKEN_KEY);

export const setPortalAuthToken = (token: string): void =>
  localStorage.setItem(PORTAL_TOKEN_KEY, token);

export const removePortalAuthToken = (): void =>
  localStorage.removeItem(PORTAL_TOKEN_KEY);
