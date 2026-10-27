export class PowerContextError extends Error {
  constructor(message, { status = 0, code = 'powercontext_error', details = null } = {}) {
    super(message);
    this.name = 'PowerContextError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export class PowerContextClient {
  constructor({ baseUrl, token = '', timeoutMs = 10000 }) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.token = token;
    this.timeoutMs = timeoutMs;
  }

  headers() {
    const headers = {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    };
    if (this.token) {
      headers.Authorization = `Bearer ${this.token}`;
    }
    return headers;
  }

  async request(path, { method = 'POST', body, timeoutMs = this.timeoutMs } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response;

    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: this.headers(),
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (error) {
      const reason =
        error?.name === 'AbortError'
          ? `PowerContext 请求超时（${timeoutMs}ms）`
          : 'PowerContext 服务不可达';
      throw new PowerContextError(reason, {
        status: 503,
        code: 'powercontext_unreachable',
        details: { path, cause: error?.message || String(error) },
      });
    } finally {
      clearTimeout(timer);
    }

    const raw = await response.text();
    let data = null;
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        data = { raw: raw.slice(0, 2000) };
      }
    }

    if (!response.ok) {
      const error = data?.error || {};
      throw new PowerContextError(
        error.message || `PowerContext 返回 HTTP ${response.status}`,
        {
          status: response.status,
          code: error.code || 'powercontext_http_error',
          details: error.details || data,
        },
      );
    }

    return data;
  }

  async health() {
    try {
      const live = await this.request('/health/live', {
        method: 'GET',
        timeoutMs: Math.min(this.timeoutMs, 4000),
      });
      let ready = null;
      try {
        ready = await this.request('/health/ready', {
          method: 'GET',
          timeoutMs: Math.min(this.timeoutMs, 4000),
        });
      } catch (error) {
        ready = { status: 'unavailable', error: error.message };
      }
      return { live, ready };
    } catch (error) {
      return {
        live: { status: 'unavailable', error: error.message },
        ready: { status: 'unavailable', error: error.message },
      };
    }
  }

  async createScope({ title, summary, idempotencyKey, ticketId }) {
    return this.request('/v1/scopes', {
      method: 'POST',
      body: {
        title,
        summary,
        idempotency_key: idempotencyKey,
        external_references: [
          {
            kind: 'memory-pawnshop-ticket',
            value: ticketId,
          },
        ],
      },
    });
  }

  async findScopeByTitle(title) {
    const params = new URLSearchParams({
      query: title,
      query_field: 'title',
      limit: '20',
    });
    const page = await this.request(`/v1/scopes?${params.toString()}`, {
      method: 'GET',
    });
    const items = Array.isArray(page?.items) ? page.items : [];
    return items.find((scope) => scope.title === title) || null;
  }

  async listMemories(scopeId) {
    return this.request('/v1/memory/entries/list', {
      method: 'POST',
      body: { scope_id: scopeId },
    });
  }

  async searchMemories(scopeId, query, limit = 6) {
    return this.request('/v1/memory/search', {
      method: 'POST',
      body: {
        scope_id: scopeId,
        query,
        limit,
        mode: 'auto',
      },
    });
  }

  async prepareContext(scopeId, query, maxBytes = 6000) {
    return this.request('/v1/context/prepare', {
      method: 'POST',
      body: {
        scope_id: scopeId,
        query,
        max_bytes: maxBytes,
        assembly: {
          format: 'markdown',
          sections: [{ family: 'memory', limit: 6 }],
        },
      },
    });
  }

  async remember({ scopeId, kind, text, reason }) {
    return this.request('/v1/memory/remember', {
      method: 'POST',
      body: {
        scope_id: scopeId,
        kind,
        text,
        reason,
      },
    });
  }

  async captureSource({ scopeId, sourceId, content, metadata }) {
    return this.request('/v1/sources/content', {
      method: 'POST',
      body: {
        scope_id: scopeId,
        source_id: sourceId,
        content,
        metadata,
      },
    });
  }
}
