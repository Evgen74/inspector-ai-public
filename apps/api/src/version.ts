/** API version (package.json), reported by /health. */
import pkg from '../package.json';

export const API_VERSION: string = pkg.version;
