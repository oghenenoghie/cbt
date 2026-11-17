/**
 * Release-pinned Ed25519 trust root for offline signing trust sets.
 *
 * Keep empty until the root key has been generated offline, independently verified, and approved
 * for a signed desktop release. Never populate this from a USB file, API response, or runtime
 * environment variable. The matching private key must never be present in this repository or API.
 */
export const OFFLINE_TRUST_ROOT_PUBLIC_KEY = "";
