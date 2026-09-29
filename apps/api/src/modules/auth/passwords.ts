/**
 * Password hashing (argon2id, OWASP minimum m=19456 KiB, t=2, p=1 — ≈10 ms on the M2 Max) and the password
 * policy of 09 §3.3.1: at least 12 characters, not the login, not a common password, not one of the last five.
 */
import { Algorithm, hash, verify } from '@node-rs/argon2';

export const ARGON2_OPTIONS = { algorithm: Algorithm.Argon2id, memoryCost: 19456, timeCost: 2, parallelism: 1 } as const;
export const MIN_PASSWORD_LENGTH = 12;
export const MAX_PASSWORD_LENGTH = 256;
export const PASSWORD_HISTORY = 5;

/** Small bundled deny-list (09 §3.3.1); compared case-insensitively. */
const COMMON_PASSWORDS = new Set([
  '123456789012',
  '1234567890123',
  'qwertyuiopas',
  'qwerty123456',
  'password1234',
  'password12345',
  'passwordpassword',
  'administrator',
  'administrator1',
  'adminadminadmin',
  'iloveyou1234',
  'letmein12345',
  'welcome12345',
  '111111111111',
  '000000000000',
  'йцукенгшщзхъ',
  'пароль123456',
  'парольпароль',
]);

export function hashPassword(password: string): Promise<string> {
  return hash(password, ARGON2_OPTIONS);
}

/** Constant-time verification; false for a malformed hash instead of throwing. */
export async function verifyPassword(passwordHash: string, password: string): Promise<boolean> {
  try {
    return await verify(passwordHash, password);
  } catch {
    return false;
  }
}

/**
 * Russian violation texts (empty = acceptable). `history` holds the previous hashes, newest first; the current
 * hash is checked by the caller as part of it.
 */
export async function passwordViolations(password: string, login: string, history: readonly string[] = []): Promise<string[]> {
  const out: string[] = [];
  if (password.length < MIN_PASSWORD_LENGTH) out.push(`короче ${MIN_PASSWORD_LENGTH} символов`);
  if (password.length > MAX_PASSWORD_LENGTH) out.push(`длиннее ${MAX_PASSWORD_LENGTH} символов`);
  if (password.trim().toLowerCase() === login.trim().toLowerCase()) out.push('совпадает с логином');
  if (COMMON_PASSWORDS.has(password.toLowerCase())) out.push('входит в список распространённых паролей');
  if (/^(.)\1+$/u.test(password)) out.push('состоит из одного повторяющегося символа');
  for (const old of history.slice(0, PASSWORD_HISTORY)) {
    if (await verifyPassword(old, password)) {
      out.push(`совпадает с одним из последних ${PASSWORD_HISTORY} паролей`);
      break;
    }
  }
  return out;
}
