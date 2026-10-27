import { existsSync, readFileSync } from 'node:fs';
import { dirname, isAbsolute, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
export const backendRoot = resolve(here, '..');
export const projectRoot = resolve(backendRoot, '..');

function loadDotEnv(filePath) {
  if (!existsSync(filePath)) {
    return;
  }

  const lines = readFileSync(filePath, 'utf8').split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) {
      continue;
    }

    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match) {
      continue;
    }

    const [, key, rawValue] = match;
    if (process.env[key] !== undefined) {
      continue;
    }

    let value = rawValue.trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    process.env[key] = value;
  }
}

loadDotEnv(process.env.PAWNSHOP_ENV_FILE || resolve(backendRoot, '.env'));

function readInt(name, fallback) {
  const parsed = Number.parseInt(process.env[name] || '', 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function readPath(name, fallback) {
  const value = process.env[name] || fallback;
  return isAbsolute(value) ? value : resolve(projectRoot, value);
}

export const config = {
  host: process.env.PAWNSHOP_HOST || '0.0.0.0',
  port: readInt('PAWNSHOP_PORT', 8765),
  dataDir: readPath('PAWNSHOP_DATA_DIR', './data'),
  apiKey: process.env.PAWNSHOP_API_KEY || '',
  maxBodyBytes: readInt('PAWNSHOP_MAX_BODY_BYTES', 64 * 1024),
  powercontextUrl: (process.env.POWERCONTEXT_URL || 'http://127.0.0.1:8000').replace(/\/+$/, ''),
  powercontextToken: process.env.POWERCONTEXT_TOKEN || '',
  powercontextTimeoutMs: readInt('POWERCONTEXT_TIMEOUT_MS', 10000),
  logLevel: (process.env.PAWNSHOP_LOG_LEVEL || 'info').toLowerCase(),
  serviceVersion: '1.0.0',
};

export function publicConfig() {
  return {
    service: 'memory-pawnshop-backend',
    version: config.serviceVersion,
    powercontext_url: config.powercontextUrl,
    data_dir: config.dataDir,
    auth_enabled: Boolean(config.apiKey),
  };
}
