#!/usr/bin/env node

import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const baseUrl = (process.env.PAWNSHOP_URL || 'http://127.0.0.1:8765').replace(/\/+$/, '');
const outputPath = resolve(root, 'evidence', 'verify-latest.json');
const stamp = Date.now();
const checks = [];
const evidence = {
  generated_at: new Date().toISOString(),
  base_url: baseUrl,
  test_mode: 'backend + PowerContext end-to-end; assistant reply is deterministic test fixture',
  checks,
};

function check(name, condition, detail = '') {
  const item = { name, passed: Boolean(condition), detail };
  checks.push(item);
  if (!item.passed) {
    throw new Error(`验收失败：${name}${detail ? `（${detail}）` : ''}`);
  }
}

async function request(path, { method = 'GET', body } = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const raw = await response.text();
  let data;
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    data = { raw };
  }
  if (!response.ok) {
    const error = new Error(`${method} ${path} -> HTTP ${response.status}`);
    error.response = data;
    throw error;
  }
  return data;
}

function sampleReply(ticketNo, lostItem, visitNo = 1) {
  return [
    `**当票 ${ticketNo} · 第 ${visitNo} 次到访**`,
    '',
    '**称重**：三毫克放学铃，外加半两风。',
    '**估价**：一枚被太阳晒热的旧硬币。',
    `**失物**：${lostItem}`,
    '**掌柜批注**：这件东西不值钱，但它认路。',
    '**赎回条件**：带一句始终没说完的话来。',
  ].join('\n');
}

async function main() {
  const ticket = `验收-${stamp.toString(36)}`;
  const redactionTicket = `脱敏-${stamp.toString(36)}`;

  const health = await request('/health');
  check('后端健康检查通过', health.ok === true, `live=${health?.powercontext?.live}`);
  check(
    'PowerContext 实际在线',
    health?.powercontext?.live === 'ok' && health?.powercontext?.ready === 'ready',
    `live=${health?.powercontext?.live}, ready=${health?.powercontext?.ready}`,
  );
  evidence.powercontext_service = health.powercontext;

  const firstContext = await request('/api/pawn/context', {
    method: 'POST',
    body: {
      ticket_id: ticket,
      query: '当票号：' + ticket + '。我想当掉一段关于小学门口辣条和一把断尺的记忆。',
      conversation_id: `verify-conv-a-${stamp}`,
      run_id: `verify-run-a-${stamp}`,
    },
  });
  check('首次到访被识别为新典当', firstContext.intent === 'pawn');
  check('首次到访计数为 1', firstContext.visit_no === 1);
  check('新当票没有伪造旧账', firstContext.is_returning === false);
  check('后端回传用户当票号', firstContext.ticket_id === ticket, firstContext.ticket_id);
  check('PowerContext scope 已创建', String(firstContext.scope_tail || '').length === 6);
  check(
    '阅读上下文经过 PowerContext',
    firstContext.powercontext?.used === true && Boolean(firstContext.powercontext?.scope_id),
  );

  const lostItem = '一把只量过身高的断尺。';
  const firstAssistant = sampleReply(firstContext.ticket_no, lostItem, 1);
  const firstSave = await request('/api/pawn/remember', {
    method: 'POST',
    body: {
      ticket_id: ticket,
      turn_id: firstContext.turn_id,
      conversation_id: `verify-conv-a-${stamp}`,
      user_memory: '我想当掉一段关于小学门口辣条和一把断尺的记忆。',
      assistant_reply: firstAssistant,
    },
  });
  check('首次典当写入成功', firstSave.saved === true);
  check('失物被结构化提取', firstSave.lost_item === lostItem, firstSave.lost_item);
  check('PowerContext 返回 scope_id', String(firstSave.powercontext?.scope_id || '').startsWith('scp_'));
  check(
    'PowerContext 返回 memory entry citation',
    String(firstSave.powercontext?.entry_id || '').startsWith('mem_ent_'),
    firstSave.powercontext?.entry_id,
  );

  evidence.first_pawn = {
    ticket_id: ticket,
    ticket_no: firstSave.ticket_no,
    lost_item: firstSave.lost_item,
    vault_count: firstSave.vault_count,
    scope_id: firstSave.powercontext?.scope_id,
    source_id: firstSave.powercontext?.source_id,
    entry_id: firstSave.powercontext?.entry_id,
    entry_version_id: firstSave.powercontext?.entry_version_id,
  };

  const replay = await request('/api/pawn/remember', {
    method: 'POST',
    body: {
      ticket_id: ticket,
      turn_id: firstContext.turn_id,
      conversation_id: `verify-conv-a-${stamp}`,
      user_memory: '重复请求不应重复封存。',
      assistant_reply: firstAssistant,
    },
  });
  check('重复写入命中幂等回放', replay.idempotent_replay === true);
  check(
    '幂等回放保留同一 entry_id',
    replay.powercontext?.entry_id === firstSave.powercontext?.entry_id,
  );

  const recallContext = await request('/api/pawn/context', {
    method: 'POST',
    body: {
      ticket_id: ticket,
      query: '当票号：' + ticket + '。我上次当掉的东西，现在怎么样了？',
      conversation_id: `verify-conv-b-${stamp}`,
      run_id: `verify-run-b-${stamp}`,
    },
  });
  check('新会话被识别为查询旧账', recallContext.intent === 'recall');
  check('新会话从账本识别为回访', recallContext.is_returning === true);
  check(
    'PowerContext 召回旧失物',
    String(recallContext.memory_block || '').includes('一把只量过身高的断尺'),
  );
  check(
    'PowerContext 召回旧原话',
    String(recallContext.memory_block || '').includes('小学门口辣条'),
  );
  check(
    '搜索命中相关旧账',
    Number(recallContext.powercontext?.search_hits || 0) > 0,
    `search_hits=${recallContext.powercontext?.search_hits}`,
  );

  const recallSave = await request('/api/pawn/remember', {
    method: 'POST',
    body: {
      ticket_id: ticket,
      turn_id: recallContext.turn_id,
      conversation_id: `verify-conv-b-${stamp}`,
      user_memory: '我上次当掉的东西，现在怎么样了？',
      assistant_reply: '**旧账 · 第 2 次翻页**\n\n**旧物**：一把只量过身高的断尺。',
    },
  });
  check('查询/赎回只读，不新增当票', recallSave.saved === false && recallSave.status === 'recall');
  check('只读查询不改变账本数量', recallSave.vault_count === 1);

  const ledger = await request(`/api/pawn/ledger?ticket_id=${encodeURIComponent(ticket)}`);
  check('账本汇总只含 1 张当票', ledger.ticket?.ticket_count === 1);
  check('账本记录两个独立会话', ledger.ticket?.conversations === 2);

  const redactionContext = await request('/api/pawn/context', {
    method: 'POST',
    body: {
      ticket_id: redactionTicket,
      query: '当票号：' + redactionTicket + '。我想当掉一段测试脱敏的记忆。',
      conversation_id: `verify-conv-redact-${stamp}`,
      run_id: `verify-run-redact-${stamp}`,
    },
  });
  const rawEmail = 'reader@example.com';
  const rawPhone = '13800138000';
  const redactionSave = await request('/api/pawn/remember', {
    method: 'POST',
    body: {
      ticket_id: redactionTicket,
      turn_id: redactionContext.turn_id,
      conversation_id: `verify-conv-redact-${stamp}`,
      user_memory: `我想当掉这段测试记忆，邮箱 ${rawEmail}，手机 ${rawPhone}。`,
      assistant_reply: sampleReply(redactionContext.ticket_no, '一张写着假邮箱的糖纸。', 1),
    },
  });
  check('脱敏测试写入成功', redactionSave.saved === true);
  check(
    '写入前识别并替换敏感信息',
    Number(redactionSave.redactions || 0) >= 2,
    `redactions=${redactionSave.redactions}`,
  );

  const redactionRecall = await request('/api/pawn/context', {
    method: 'POST',
    body: {
      ticket_id: redactionTicket,
      query: '当票号：' + redactionTicket + '。我的旧账里写了什么？',
      conversation_id: `verify-conv-redact-read-${stamp}`,
      run_id: `verify-run-redact-read-${stamp}`,
    },
  });
  const redactedBlock = String(redactionRecall.memory_block || '');
  check('旧账中不再出现原始邮箱', !redactedBlock.includes(rawEmail));
  check('旧账中不再出现原始手机号', !redactedBlock.includes(rawPhone));
  check('旧账包含脱敏占位符', redactedBlock.includes('[已隐去的邮箱]'));

  evidence.recall = {
    conversation_id: `verify-conv-b-${stamp}`,
    visit_no: recallContext.visit_no,
    search_hits: recallContext.powercontext?.search_hits,
    context_status: recallContext.context_status,
    memory_block_excerpt: String(recallContext.memory_block || '').slice(0, 1400),
    read_only: recallSave.saved === false,
  };
  evidence.redaction = {
    ticket_id: redactionTicket,
    redactions: redactionSave.redactions,
    entry_id: redactionSave.powercontext?.entry_id,
  };
  evidence.ledger = ledger.ticket;
  evidence.result = 'passed';

  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(evidence, null, 2));
  console.log(`\n验收通过，证据已写入 ${outputPath}`);
}

main().catch(async (error) => {
  evidence.result = 'failed';
  evidence.error = { message: error.message, response: error.response || null };
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
