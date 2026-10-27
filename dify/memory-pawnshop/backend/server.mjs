import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';
import { config, publicConfig } from './lib/config.mjs';
import { Ledger } from './lib/ledger.mjs';
import { PowerContextClient, PowerContextError } from './lib/powercontext.mjs';
import { PawnshopService, ServiceError } from './lib/service.mjs';

const ledger = new Ledger(resolve(config.dataDir, 'ledger.json'));
await ledger.init();

const powercontext = new PowerContextClient({
  baseUrl: config.powercontextUrl,
  token: config.powercontextToken,
  timeoutMs: config.powercontextTimeoutMs,
});
const service = new PawnshopService({ config, ledger, powercontext });

const LOG_LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };

function log(level, event, data = {}) {
  if ((LOG_LEVELS[level] || 20) < (LOG_LEVELS[config.logLevel] || 20)) {
    return;
  }
  console.log(
    JSON.stringify({
      ts: new Date().toISOString(),
      level,
      event,
      ...data,
    }),
  );
}

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type,X-Pawnshop-Key,X-Request-Id',
    'Access-Control-Max-Age': '600',
  };
}

function sendJson(res, status, payload, requestId) {
  const body = `${JSON.stringify(payload)}\n`;
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
    'X-Request-Id': requestId,
    ...corsHeaders(),
  });
  res.end(body);
}

async function readJson(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > config.maxBodyBytes) {
      throw new ServiceError('请求体过大。', {
        status: 413,
        code: 'body_too_large',
      });
    }
    chunks.push(chunk);
  }

  if (size === 0) {
    return {};
  }

  const raw = Buffer.concat(chunks).toString('utf8');
  try {
    return JSON.parse(raw);
  } catch {
    throw new ServiceError('请求体不是合法 JSON。', {
      status: 400,
      code: 'invalid_json',
    });
  }
}

function requireString(value, field) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new ServiceError(`缺少字段：${field}`, {
      status: 400,
      code: 'missing_field',
      details: { field },
    });
  }
  return value;
}

function authorized(req) {
  if (!config.apiKey) {
    return true;
  }
  return req.headers['x-pawnshop-key'] === config.apiKey;
}

const server = http.createServer(async (req, res) => {
  const requestId = randomUUID();
  const startedAt = Date.now();
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);

  res.on('finish', () => {
    log('info', 'http_request', {
      request_id: requestId,
      method: req.method,
      path: url.pathname,
      status: res.statusCode,
      duration_ms: Date.now() - startedAt,
    });
  });

  if (req.method === 'OPTIONS') {
    res.writeHead(204, corsHeaders());
    res.end();
    return;
  }

  try {
    if (req.method === 'GET' && url.pathname === '/health') {
      const health = await service.health();
      sendJson(res, 200, health, requestId);
      return;
    }

    if (req.method === 'GET' && url.pathname === '/') {
      sendJson(
        res,
        200,
        {
          ...publicConfig(),
          endpoints: {
            health: 'GET /health',
            context: 'POST /api/pawn/context',
            remember: 'POST /api/pawn/remember',
            ledger: 'GET /api/pawn/ledger?ticket_id=...',
          },
        },
        requestId,
      );
      return;
    }

    if (url.pathname.startsWith('/api/') && !authorized(req)) {
      sendJson(
        res,
        401,
        {
          ok: false,
          error: {
            code: 'unauthorized',
            message: '请提供正确的 X-Pawnshop-Key。',
          },
        },
        requestId,
      );
      return;
    }

    if (req.method === 'POST' && url.pathname === '/api/pawn/context') {
      const body = await readJson(req);
      const result = await service.getContext({
        ticketId: requireString(body.ticket_id, 'ticket_id'),
        query: requireString(body.query, 'query'),
        conversationId: body.conversation_id,
        runId: body.run_id,
      });
      sendJson(res, 200, result, requestId);
      return;
    }

    if (req.method === 'POST' && url.pathname === '/api/pawn/remember') {
      const body = await readJson(req);
      const result = await service.remember({
        ticketId: requireString(body.ticket_id, 'ticket_id'),
        turnId: requireString(body.turn_id, 'turn_id'),
        conversationId: body.conversation_id,
        userMemory: requireString(body.user_memory, 'user_memory'),
        assistantReply: requireString(body.assistant_reply, 'assistant_reply'),
      });
      sendJson(res, 200, result, requestId);
      return;
    }

    if (req.method === 'GET' && url.pathname === '/api/pawn/ledger') {
      const ticketId = requireString(url.searchParams.get('ticket_id'), 'ticket_id');
      const result = service.getLedger(ticketId);
      sendJson(res, 200, result, requestId);
      return;
    }

    sendJson(
      res,
      404,
      {
        ok: false,
        error: {
          code: 'not_found',
          message: '没有这个端点。',
        },
      },
      requestId,
    );
  } catch (error) {
    if (error instanceof ServiceError) {
      sendJson(
        res,
        error.status,
        {
          ok: false,
          error: {
            code: error.code,
            message: error.message,
            details: error.details,
          },
        },
        requestId,
      );
      return;
    }

    if (error instanceof PowerContextError) {
      log('error', 'powercontext_error', {
        request_id: requestId,
        path: url.pathname,
        status: error.status,
        code: error.code,
        message: error.message,
      });
      sendJson(
        res,
        502,
        {
          ok: false,
          error: {
            code: 'powercontext_unavailable',
            message: '当铺账本暂时打不开。请确认 PowerContext 已启动后再试。',
            details: {
              powercontext_code: error.code,
              powercontext_status: error.status,
            },
          },
        },
        requestId,
      );
      return;
    }

    log('error', 'unhandled_error', {
      request_id: requestId,
      path: url.pathname,
      message: error?.message || String(error),
      stack: error?.stack,
    });
    sendJson(
      res,
      500,
      {
        ok: false,
        error: {
          code: 'internal_error',
          message: '掌柜把算盘打翻了。请稍后再试。',
        },
      },
      requestId,
    );
  }
});

server.listen(config.port, config.host, () => {
  log('info', 'server_started', {
    host: config.host,
    port: config.port,
    powercontext_url: config.powercontextUrl,
    data_dir: config.dataDir,
  });
});

function shutdown(signal) {
  log('info', 'server_stopping', { signal });
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 5000).unref();
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
