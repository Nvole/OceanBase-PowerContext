import { existsSync } from 'node:fs';
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';
import {
  detectIntent,
  normalizeConversationId,
  normalizeTicketId,
  scrubText,
  shortHash,
  truncateUtf8,
} from './text.mjs';

const LEDGER_VERSION = 1;

function emptyLedger() {
  return {
    version: LEDGER_VERSION,
    created_at: new Date().toISOString(),
    tickets: {},
    turns: {},
  };
}

export class Ledger {
  constructor(filePath) {
    this.filePath = filePath;
    this.data = emptyLedger();
    this.writeChain = Promise.resolve();
  }

  async init() {
    if (existsSync(this.filePath)) {
      const raw = await readFile(this.filePath, 'utf8');
      const parsed = JSON.parse(raw);
      this.data = {
        ...emptyLedger(),
        ...parsed,
        tickets: parsed.tickets || {},
        turns: parsed.turns || {},
      };
    } else {
      await this.persist();
    }
  }

  ticketKey(ticketId) {
    return shortHash(normalizeTicketId(ticketId).toLocaleLowerCase('zh-CN'), 24);
  }

  ensureTicket(ticketId) {
    const normalized = normalizeTicketId(ticketId);
    const key = this.ticketKey(normalized);
    if (!this.data.tickets[key]) {
      this.data.tickets[key] = {
        ticket_key: key,
        ticket_id: normalized,
        scope_id: null,
        created_at: new Date().toISOString(),
        last_seen_at: new Date().toISOString(),
        visits: 0,
        ticket_count: 0,
        last_ticket_no: null,
        last_item: '',
        last_memory: '',
        conversations: {},
      };
    }
    return this.data.tickets[key];
  }

  getTicket(ticketId) {
    return this.data.tickets[this.ticketKey(ticketId)] || null;
  }

  async setScope(ticketId, scopeId) {
    const ticket = this.ensureTicket(ticketId);
    ticket.scope_id = scopeId;
    ticket.last_seen_at = new Date().toISOString();
    await this.persist();
    return ticket;
  }

  async beginTurn({ ticketId, query, conversationId = '', runId = '' }) {
    const normalized = normalizeTicketId(ticketId);
    const cleanConversationId = normalizeConversationId(conversationId);

    if (runId && this.data.turns[runId]) {
      return { turn: this.data.turns[runId], reused: true };
    }

    const ticket = this.ensureTicket(normalized);
    const conversationKey = cleanConversationId
      ? shortHash(cleanConversationId, 20)
      : 'anonymous';
    const now = new Date().toISOString();

    if (!ticket.conversations[conversationKey]) {
      ticket.visits += 1;
    }
    ticket.conversations[conversationKey] = {
      first_seen_at: ticket.conversations[conversationKey]?.first_seen_at || now,
      last_seen_at: now,
      turns:
        (ticket.conversations[conversationKey]?.turns || 0) + 1,
    };
    ticket.last_seen_at = now;

    const intent = detectIntent(query);
    const visitNo = ticket.visits;
    const ticketPrefix = ticket.ticket_key.slice(0, 3).toUpperCase();
    const ticketNo =
      intent === 'recall'
        ? ticket.last_ticket_no || `MP-${ticketPrefix}-000`
        : `MP-${ticketPrefix}-${String(ticket.ticket_count + 1).padStart(3, '0')}`;

    const turn = {
      turn_id: runId || randomUUID(),
      ticket_key: ticket.ticket_key,
      ticket_id: normalized,
      conversation_id: cleanConversationId,
      query: truncateUtf8(scrubText(query).text, 600),
      visit_no: visitNo,
      intent,
      ticket_no: ticketNo,
      status: 'open',
      created_at: now,
      updated_at: now,
    };

    this.data.turns[turn.turn_id] = turn;
    this.pruneTurns();
    await this.persist();
    return { turn, reused: false };
  }

  getTurn(turnId) {
    return this.data.turns[turnId] || null;
  }

  async markTurn(turnId, status, patch = {}) {
    const turn = this.data.turns[turnId];
    if (!turn) {
      return null;
    }

    const previousStatus = turn.status;
    const ticket = this.data.tickets[turn.ticket_key];
    const now = new Date().toISOString();

    if (status === 'saved' && previousStatus !== 'saved' && ticket) {
      ticket.ticket_count += 1;
      ticket.last_ticket_no = turn.ticket_no;
      ticket.last_item = patch.last_item || '';
      ticket.last_memory = patch.last_memory || '';
      ticket.last_seen_at = now;
    }

    Object.assign(turn, patch, {
      status,
      updated_at: now,
    });

    await this.persist();
    return turn;
  }

  getTicketSummary(ticketId) {
    const ticket = this.getTicket(ticketId);
    if (!ticket) {
      return null;
    }

    const recentTurns = Object.values(this.data.turns)
      .filter((turn) => turn.ticket_key === ticket.ticket_key)
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
      .slice(0, 8)
      .map((turn) => ({
        turn_id: turn.turn_id,
        visit_no: turn.visit_no,
        intent: turn.intent,
        ticket_no: turn.ticket_no,
        status: turn.status,
        created_at: turn.created_at,
        updated_at: turn.updated_at,
      }));

    return {
      ticket_id: ticket.ticket_id,
      ticket_key_tail: ticket.ticket_key.slice(-6),
      scope_tail: ticket.scope_id ? ticket.scope_id.slice(-6) : null,
      created_at: ticket.created_at,
      last_seen_at: ticket.last_seen_at,
      visits: ticket.visits,
      ticket_count: ticket.ticket_count,
      last_ticket_no: ticket.last_ticket_no,
      last_item: ticket.last_item,
      conversations: Object.keys(ticket.conversations).length,
      recent_turns: recentTurns,
    };
  }

  pruneTurns() {
    const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
    const entries = Object.entries(this.data.turns);
    for (const [turnId, turn] of entries) {
      if (Date.parse(turn.created_at) < cutoff) {
        delete this.data.turns[turnId];
      }
    }

    const remaining = Object.entries(this.data.turns);
    if (remaining.length <= 500) {
      return;
    }

    remaining
      .sort(([, a], [, b]) => a.created_at.localeCompare(b.created_at))
      .slice(0, remaining.length - 500)
      .forEach(([turnId]) => delete this.data.turns[turnId]);
  }

  async persist() {
    const payload = `${JSON.stringify(this.data, null, 2)}\n`;
    this.writeChain = this.writeChain.then(async () => {
      await mkdir(dirname(this.filePath), { recursive: true });
      const temporaryPath = `${this.filePath}.${process.pid}.${Date.now()}.tmp`;
      await writeFile(temporaryPath, payload, 'utf8');
      try {
        await rename(temporaryPath, this.filePath);
      } catch {
        await writeFile(this.filePath, payload, 'utf8');
        await rm(temporaryPath, { force: true });
      }
    });
    return this.writeChain;
  }
}
