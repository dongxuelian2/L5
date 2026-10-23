import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const local = resolve(process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const executable = process.env.PYTHON || (existsSync(local) ? local : process.platform === 'win32' ? 'python' : 'python3');
const child = spawnSync(executable, process.argv.slice(2), {
  stdio: 'inherit',
  env: { ...process.env, PYTHONUTF8: '1' },
});
if (child.error) console.error(`Cannot run ${executable}: ${child.error.message}. Set PYTHON to your Python executable.`);
process.exit(child.status ?? 1);
