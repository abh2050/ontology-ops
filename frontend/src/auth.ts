import { createRemoteJWKSet, jwtVerify } from "jose";

interface Config {
  auth_mode: "local" | "cognito";
  domain: string | null;
  client_id: string | null;
  issuer: string | null;
}
let config: Config;
const callback = `${window.location.origin}/auth/callback`;
const b64url = (bytes: Uint8Array) =>
  btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
const random = () => b64url(crypto.getRandomValues(new Uint8Array(48)));
export function hasToken() {
  return Boolean(
    sessionStorage.getItem("ops_access_token") ||
    sessionStorage.getItem("ops_local_token"),
  );
}
export function canUseCognito() {
  return Boolean(config?.domain && config?.client_id);
}
export function localAuth() {
  return config?.auth_mode === "local";
}
export async function initializeAuth() {
  const response = await fetch("/ui-config.json", { cache: "no-store" });
  if (!response.ok) throw new Error("Unable to load sign-in configuration.");
  config = await response.json();
  await completeCallback();
}
export async function signIn() {
  if (!canUseCognito()) throw new Error("Cognito UI configuration is missing.");
  const verifier = random(),
    state = random(),
    nonce = random();
  const challenge = b64url(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)),
    ),
  );
  sessionStorage.setItem(
    "ops_oauth",
    JSON.stringify({ verifier, state, nonce, created: Date.now() }),
  );
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id!,
    redirect_uri: callback,
    scope: "openid profile",
    code_challenge_method: "S256",
    code_challenge: challenge,
    state,
    nonce,
  });
  window.location.assign(`${config.domain}/oauth2/authorize?${params}`);
}
async function completeCallback() {
  if (window.location.pathname !== "/auth/callback") return;
  const params = new URLSearchParams(window.location.search);
  const stored = sessionStorage.getItem("ops_oauth");
  sessionStorage.removeItem("ops_oauth");
  window.history.replaceState({}, "", "/");
  if (!stored)
    throw new Error("Sign-in session is missing. Start sign-in again.");
  const pending = JSON.parse(stored);
  if (
    params.get("state") !== pending.state ||
    Date.now() - pending.created > 10 * 60 * 1000
  )
    throw new Error("Sign-in state is invalid or expired.");
  if (params.has("error"))
    throw new Error("Sign-in was declined. Start sign-in again.");
  if (!params.get("code") || !config.issuer || !canUseCognito())
    throw new Error("Sign-in callback is incomplete.");
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.client_id!,
    code: params.get("code")!,
    redirect_uri: callback,
    code_verifier: pending.verifier,
  });
  const response = await fetch(`${config.domain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok)
    throw new Error("Cognito token exchange failed. Start sign-in again.");
  const tokens = await response.json();
  const keys = createRemoteJWKSet(
    new URL(`${config.issuer}/.well-known/jwks.json`),
  );
  const verified = await jwtVerify(tokens.id_token, keys, {
    issuer: config.issuer,
    audience: config.client_id!,
    algorithms: ["RS256"],
  });
  if (
    verified.payload.nonce !== pending.nonce ||
    verified.payload.token_use !== "id"
  )
    throw new Error("Sign-in nonce validation failed.");
  sessionStorage.setItem("ops_access_token", tokens.access_token);
}
export function signOut() {
  sessionStorage.removeItem("ops_access_token");
  sessionStorage.removeItem("ops_local_token");
  if (canUseCognito())
    window.location.assign(
      `${config.domain}/logout?${new URLSearchParams({ client_id: config.client_id!, logout_uri: `${window.location.origin}/` })}`,
    );
  else window.location.reload();
}
