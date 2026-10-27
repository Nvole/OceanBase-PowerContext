import { createHash } from 'node:crypto';

export function sha256(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

export function shortHash(value, length = 12) {
  return sha256(value).slice(0, length);
}

export function normalizeTicketId(value) {
  if (typeof value !== 'string') {
    throw new Error('当票号必须是文字。');
  }

  const cleaned = value
    .normalize('NFC')
    .replace(/[\u0000-\u001F\u007F]/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  const characters = Array.from(cleaned);
  if (characters.length === 0) {
    throw new Error('请先取一个当票号。');
  }
  if (characters.length > 24) {
    throw new Error('当票号最多 24 个字符。');
  }
  if (/^(?:https?:\/\/|www\.)/i.test(cleaned)) {
    throw new Error('当票号不能是网址。');
  }

  return characters.join('');
}

export function normalizeConversationId(value) {
  if (typeof value !== 'string') {
    return '';
  }
  return value.replace(/[\u0000-\u001F\u007F]/g, '').trim().slice(0, 200);
}

export function normalizeRunId(value) {
  if (typeof value !== 'string') {
    return '';
  }
  return value.replace(/[^A-Za-z0-9._:-]/g, '').slice(0, 128);
}

const REDACTION_RULES = [
  [/\bsk-[A-Za-z0-9_-]{12,}\b/g, '[已隐去的密钥]'],
  [/\bBearer\s+[A-Za-z0-9._\-+/=]{8,}/gi, 'Bearer [已隐去的令牌]'],
  [/\b\d{17}[\dXx]\b/g, '[已隐去的证件号]'],
  [/\b1[3-9]\d{9}\b/g, '[已隐去的手机号]'],
  [/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, '[已隐去的邮箱]'],
];

export function scrubText(value) {
  let text = typeof value === 'string' ? value : '';
  let redactions = 0;

  for (const [pattern, replacement] of REDACTION_RULES) {
    text = text.replace(pattern, () => {
      redactions += 1;
      return replacement;
    });
  }

  return { text, redactions };
}

export function truncateUtf8(value, maxBytes, suffix = '…') {
  const text = typeof value === 'string' ? value : String(value ?? '');
  if (Buffer.byteLength(text, 'utf8') <= maxBytes) {
    return text;
  }

  const suffixBytes = Buffer.byteLength(suffix, 'utf8');
  const budget = Math.max(0, maxBytes - suffixBytes);
  let end = text.length;
  while (end > 0 && Buffer.byteLength(text.slice(0, end), 'utf8') > budget) {
    end -= 1;
  }
  return `${text.slice(0, end)}${suffix}`;
}

export function normalizeWhitespace(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

export function detectIntent(query) {
  const text = normalizeWhitespace(query).toLowerCase();
  const recallPattern = /(赎回|上次|上回|之前|以前|旧账|还记得|记得我|旧物|旧当票|当票|后来|怎么了|看看|查一下|查询)/;
  const pawnPattern = /(当掉|典当|我想当|收下|押上|存进|封存|换一件|换点|这段记忆|一段记忆)/;
  const strongRecallPattern = /(赎回|上次|上回|之前|以前|旧账|还记得|记得我|旧物|旧当票|后来|怎么了)/;
  const newPawnPattern = /(我想当|再当|当掉一段|典当一段|收下这段|押上这段)/;

  const wantsRecall = recallPattern.test(text);
  const wantsPawn = pawnPattern.test(text);

  if (strongRecallPattern.test(text) && !newPawnPattern.test(text)) {
    return 'recall';
  }
  if (wantsRecall && !wantsPawn) {
    return 'recall';
  }
  return 'pawn';
}

export function isRecallQuery(query) {
  return detectIntent(query) === 'recall';
}

export function isGreetingOrEmpty(query) {
  const text = normalizeWhitespace(query);
  if (!text) {
    return true;
  }
  if (text.length < 4) {
    return true;
  }
  return /^(你好|您好|hi|hello|在吗|嗨|哈喽|早上好|晚上好|谢谢|多谢)[！!。.~～\s]*$/i.test(text);
}

export function extractLostItem(assistantReply) {
  const text = String(assistantReply || '');
  const patterns = [
    /\*\*失物\*\*\s*[：:]\s*([^\n]+)/,
    /失物\s*[：:]\s*\**([^\n*]+)\**/,
    /失物\s*[：:]\s*([^\n]+)/,
  ];

  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match?.[1]) {
      return normalizeWhitespace(match[1]).slice(0, 160);
    }
  }
  return '';
}

export function hashToInt(value) {
  const digest = sha256(value);
  return Number.parseInt(digest.slice(0, 8), 16);
}

export function shanghaiDateKey(date = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
}
