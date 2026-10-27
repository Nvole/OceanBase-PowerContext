#!/usr/bin/env node

const baseUrl = (process.env.PAWNSHOP_URL || 'http://127.0.0.1:8765').replace(/\/+$/, '');
const ticketId = process.argv[2] || '小满';
const stamp = Date.now();

async function post(path, body) {
  const response = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}: ${JSON.stringify(data)}`);
  }
  return data;
}

async function main() {
  const query = `当票号：${ticketId}。我想当掉一段关于小学门口辣条和一把断尺的记忆。`;
  const context = await post('/api/pawn/context', {
    ticket_id: ticketId,
    query,
    conversation_id: `seed-conv-${stamp}`,
    run_id: `seed-run-${stamp}`,
  });

  if (context.vault_count > 0) {
    console.log(JSON.stringify({ seeded: false, reason: '这个当票号已经有旧账，无需重复初始化。', context }, null, 2));
    return;
  }

  const lostItem = '一把只量过身高的断尺。';
  const reply = [
    `**当票 ${context.ticket_no} · 第 ${context.visit_no} 次到访**`,
    '',
    '**称重**：三毫克放学铃，外加半两风。',
    '**估价**：一枚被太阳晒热的旧硬币。',
    `**失物**：${lostItem}`,
    '**掌柜批注**：这件东西不值钱，但它认得回来的路。',
    '**赎回条件**：带一句始终没说完的话来。',
  ].join('\n');

  const saved = await post('/api/pawn/remember', {
    ticket_id: ticketId,
    turn_id: context.turn_id,
    conversation_id: `seed-conv-${stamp}`,
    user_memory: '我想当掉一段关于小学门口辣条和一把断尺的记忆。',
    assistant_reply: reply,
  });

  console.log(JSON.stringify({
    seeded: true,
    ticket_id: ticketId,
    ticket_no: saved.ticket_no,
    lost_item: saved.lost_item,
    vault_count: saved.vault_count,
    scope_id: saved.powercontext?.scope_id,
    entry_id: saved.powercontext?.entry_id,
    next_step: `回到 Dify 新开会话，输入：当票号：${ticketId}。我上次当掉的东西，现在怎么样了？`,
  }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
