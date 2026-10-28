import { SeekdbClient } from 'seekdb';
import { writeFile } from 'node:fs/promises';

const database = process.env.SEEKDB_DATABASE || 'stepfun_kb';
if (!/^stepfun_[a-z0-9_]+$/.test(database)) throw new Error('Only stepfun_ databases permitted');
const client = new SeekdbClient({ host: process.env.SEEKDB_HOST || '127.0.0.1', port: Number(process.env.SEEKDB_PORT || 2881), user: process.env.SEEKDB_USER || 'root', password: process.env.SEEKDB_PASSWORD || '', database });
try {
  const tables = await client.execute('SHOW TABLES');
  const table = tables.map(row => Object.values(row)[0]).find(name => /^c\$v2\$[a-f0-9]+$/.test(name));
  if (!table) throw new Error('No SDK collection table found; import documents first');
  const ddl = await client.execute(`SHOW CREATE TABLE \`${table}\``);
  const indexes = await client.execute(`SHOW INDEX FROM \`${table}\``);
  const version = await client.execute('SELECT VERSION() AS version');
  await writeFile('evidence/database-schema.json', JSON.stringify({ database, version, table, ddl, indexes }, null, 2) + '\n');
  console.log('Saved real collection schema and indexes');
} finally { await client.close(); }
