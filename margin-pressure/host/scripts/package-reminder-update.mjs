// Produce a small offline updater for the already-installed Windows host.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const here = fileURLToPath(new URL('../', import.meta.url));
const output = resolve(process.argv[2] || resolve(here, 'data-link-update'));
const compatible = {
  'server.mjs': ['d3fa461bf38367a434f6ea581e99c94441b366fe4968fcb3dbf3ad6ef90cff31', 'ab77a91743c1e68129ca593e6bed829cf0623a3a9106fa5cf5afcc15f8a04b6e', 'b4e81e93f2ddd88323e20cea7534783db688cd0a9110f8d46774fbdc87f7958e'],
  'frontend.mjs': ['297fcf718053481ff95ae839fe45465d52741e33331c57b45c4307c77933b36b', 'a8f9afc167adcac6d73622e427deea5dc527b7c898cef8a33b57a2f06ee3bcc2', '4a34afb5e31e14e4c2b4837c2db68d132226604b3d974f9668f1f90b67eb0f94'],
  'input-status.mjs': ['c9e2ee7f78140a9a0a8a381a7184043c591bd9e9b2ae498cf61bd8c5b5a6a229', '81d0632310071c3c698b63f5a2d0c2f3a55472369918a0244262707e692d21be']
};
const files = await Promise.all(['server.mjs', 'frontend.mjs', 'input-status.mjs', 'data-source.mjs', 'xlsx-dates.mjs'].map(async name => {
  const bytes = await readFile(resolve(here, name));
  return { name, previousHashes: compatible[name] || [], allowMissing: !['server.mjs', 'frontend.mjs'].includes(name), updatedHash: createHash('sha256').update(bytes).digest('hex'), content: bytes.toString('base64') };
}));
const installer = `import {readFile,writeFile,copyFile,rename,unlink} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
const root=fileURLToPath(new URL('.',import.meta.url));
const files=${JSON.stringify(files)};
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const pending=[];
try {
  for(const file of files){
    const target=join(root,file.name);
    let before=null;
    try{before=await readFile(target)}catch(error){if(error.code!=='ENOENT')throw error}
    if(before&&digest(before)===file.updatedHash)continue;
    if(before?!file.previousHashes.includes(digest(before)):!file.allowMissing){
      throw new Error('Unexpected existing file: '+file.name+'. No files changed.');
    }
    const bytes=Buffer.from(file.content,'base64');
    if(digest(bytes)!==file.updatedHash)throw new Error('Update integrity check failed.');
    pending.push({target,before,bytes,temp:target+'.data-link.pending',installed:false});
  }
  const stamp=new Date().toISOString().replace(/[:.]/g,'-');
  for(const item of pending){
    await writeFile(item.temp,item.bytes,{flag:'wx'});item.staged=true;
    if(item.before)await copyFile(item.target,item.target+'.before-data-link-'+stamp+'.bak',1);
  }
  for(const item of pending){await rename(item.temp,item.target);item.staged=false;item.installed=true}
  console.log(pending.length?'Analysis data link installed successfully.':'Analysis data link is already installed.');
  console.log('Close the running server window, then run start-fixed.cmd again.');
  console.log('Open http://127.0.0.1:8787/?stock=2492 and refresh the page.');
}catch(error){
  for(const item of [...pending].reverse()){
    if(item.installed){if(item.before)await writeFile(item.target,item.before);else await unlink(item.target).catch(()=>{})}
    if(item.staged)await unlink(item.temp).catch(()=>{});
  }
  console.error('Update failed: '+error.message);process.exitCode=1;
}
`;
const launcher = ['@echo off', 'setlocal EnableExtensions DisableDelayedExpansion', 'cd /d "%~dp0"', 'where node.exe >nul 2>&1', 'if errorlevel 1 goto missing_node', 'node.exe "%~dp0apply-data-link.mjs"', 'set "radar_update_exit=%errorlevel%"', 'pause', 'exit /b %radar_update_exit%', ':missing_node', 'echo Install Node.js 22 or newer, then run this file again.', 'pause', 'exit /b 1', ''].join('\r\n');
await mkdir(output, { recursive: true });
await writeFile(resolve(output, 'apply-data-link.mjs'), installer);
await writeFile(resolve(output, 'install-data-link.cmd'), launcher, 'ascii');
console.log(`Created offline update files in ${output}`);
