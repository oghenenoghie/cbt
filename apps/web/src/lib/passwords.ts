// Suggested passwords follow the API's own generator (app/core/passwords.py): no look-alike
// characters, so they can be read out or copied by hand, and two more characters than the
// minimum (14 for staff, 10 for students). The API still checks every password it is sent.

const ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";

export function minimumPasswordLength(role: string): number {
  return role === "student" ? 8 : 12;
}

export function suggestPassword(role: string): string {
  const length = minimumPasswordLength(role) + 2;
  const chosen: string[] = [];
  // Rejection sampling keeps every character equally likely.
  const limit = 256 - (256 % ALPHABET.length);
  const bytes = new Uint8Array(64);
  while (chosen.length < length) {
    crypto.getRandomValues(bytes);
    for (const byte of bytes) {
      if (byte < limit && chosen.length < length) chosen.push(ALPHABET[byte % ALPHABET.length]);
    }
  }
  return chosen.join("");
}
