import { build } from 'esbuild';
import { mkdir, copyFile, readdir } from 'node:fs/promises';
await mkdir('dist/vendor/ort', { recursive: true });
await build({ entryPoints: ['web/app.js', 'web/embedding.worker.js'], outdir: 'dist', bundle: true, format: 'esm', platform: 'browser', target: 'es2022', sourcemap: true, loader: { '.wasm': 'file' } });
for (const file of ['index.html', 'style.css']) await copyFile(`web/${file}`, `dist/${file}`);
for (const name of await readdir('node_modules/onnxruntime-web/dist')) if (name.endsWith('.wasm') || name.startsWith('ort-wasm') && name.endsWith('.mjs')) await copyFile(`node_modules/onnxruntime-web/dist/${name}`, `dist/vendor/ort/${name}`);
console.log('Browser inference bundle built.');
